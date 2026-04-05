from __future__ import annotations

import importlib
import sys
from pathlib import Path

from cambc import EntityType, Position


JON_6_A4_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a4bfs"
)
for module_name in ("core_bot", "logger", "marker", "utils"):
    sys.modules.pop(module_name, None)
if str(JON_6_A4_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A4_BFS_ROOT))
importlib.invalidate_caches()

import builder_bot as builder_bot_module
import core_bot as core_bot_module
from core_bot import CoreBot
from builder_bot import BuilderBot


class _StubLogger:
    def log(self, _message: str) -> None:
        return

    def print(self, _message: str) -> None:
        return


class _StubController:
    def __init__(
        self,
        *,
        round_num: int,
        titanium: int = 1000,
        can_place_marker: bool = True,
    ) -> None:
        self._round_num = round_num
        self._titanium = titanium
        self._can_place_marker = can_place_marker
        self.spawned_positions: list[Position] = []
        self._core_pos = Position(10, 10)

    def get_current_round(self) -> int:
        return self._round_num

    def get_global_resources(self) -> tuple[int, int]:
        return (self._titanium, 0)

    def get_position(self) -> Position:
        return self._core_pos

    def can_spawn(self, _position: Position) -> bool:
        return True

    def spawn_builder(self, position: Position) -> None:
        self.spawned_positions.append(position)

    def get_nearby_entities(self):
        return []

    def get_entity_type(self, _entity_id):
        return EntityType.MARKER

    def get_team(self, _entity_id=None):
        return 1

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30

    def can_place_marker(self, _position: Position) -> bool:
        return self._can_place_marker

    def place_marker(self, _position: Position, _value: int) -> None:
        return


class _BuilderInitController:
    def __init__(
        self,
        *,
        position: Position,
        core_pos: Position,
        round_num: int,
        marker_value: int | None = None,
    ) -> None:
        self._position = position
        self._core_pos = core_pos
        self._round_num = round_num
        self._marker_value = marker_value

    def get_position(self, entity_id=None) -> Position:
        if entity_id is None:
            return self._position
        return self._core_pos

    def get_current_round(self) -> int:
        return self._round_num

    def get_nearby_entities(self):
        entities = [1]
        if self._marker_value is not None:
            entities.append(2)
        return entities

    def get_entity_type(self, entity_id):
        if entity_id == 1:
            return EntityType.CORE
        assert entity_id == 2
        return EntityType.MARKER

    def get_team(self, _entity_id=None):
        return 1

    def get_marker_value(self, entity_id):
        assert entity_id == 2
        return self._marker_value

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30


def _is_diagonal_spawn(core_pos: Position, spawn_pos: Position) -> bool:
    return abs(spawn_pos.x - core_pos.x) == 1 and abs(spawn_pos.y - core_pos.y) == 1


def test_first_two_assault_spawns_happen_on_turns_five_and_six(monkeypatch):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())
    monkeypatch.setattr(core_bot_module.random, "shuffle", lambda _items: None)

    bot = CoreBot()
    spawn_records: list[tuple[int, Position]] = []

    for round_num in range(1, 7):
        controller = _StubController(round_num=round_num)
        bot.run(controller)
        if controller.spawned_positions:
            spawn_records.append((round_num, controller.spawned_positions[0]))

    assert [round_num for round_num, _ in spawn_records] == [1, 2, 3, 4, 5, 6]
    assert all(
        not _is_diagonal_spawn(Position(10, 10), spawn_pos)
        for _, spawn_pos in spawn_records[:4]
    )
    assert all(
        _is_diagonal_spawn(Position(10, 10), spawn_pos)
        for _, spawn_pos in spawn_records[4:6]
    )
    assert bot.assault_spawned == 2


def test_third_assault_spawn_is_not_forced_on_turn_seven(monkeypatch):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())
    monkeypatch.setattr(core_bot_module.random, "shuffle", lambda _items: None)

    bot = CoreBot()
    spawn_rounds: list[int] = []

    for round_num in range(1, 8):
        controller = _StubController(round_num=round_num)
        bot.run(controller)
        if controller.spawned_positions:
            spawn_rounds.append(round_num)

    assert spawn_rounds == [1, 2, 3, 4, 5, 6]
    assert bot.assault_spawned == 2


def test_bonus_assault_spawn_does_not_require_spawn_marker(monkeypatch):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())
    monkeypatch.setattr(core_bot_module.random, "shuffle", lambda _items: None)

    bot = CoreBot()
    spawn_records: list[tuple[int, Position]] = []

    for round_num in range(1, 20):
        controller = _StubController(round_num=round_num, can_place_marker=False)
        bot.run(controller)
        if controller.spawned_positions:
            spawn_records.append((round_num, controller.spawned_positions[0]))

    assert [round_num for round_num, _ in spawn_records] == [1, 2, 3, 4, 5, 6, 19]
    assert _is_diagonal_spawn(Position(10, 10), spawn_records[6][1])
    assert bot.assault_spawned == 3


def test_second_opening_assault_builder_stays_assault_on_first_turn_seven(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(1, 26),
        core_pos=Position(2, 27),
        round_num=7,
    )

    bot._init_turn(controller)

    assert bot.is_assault_role is True


def test_diagonal_builder_spawn_after_opening_stays_assault_role(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(11, 9),
        core_pos=Position(10, 10),
        round_num=19,
    )

    bot._init_turn(controller)

    assert bot.is_assault_role is True


def test_cardinal_builder_spawn_stays_economy_role(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(10, 9),
        core_pos=Position(10, 10),
        round_num=19,
    )

    bot._init_turn(controller)

    assert bot.is_assault_role is False
