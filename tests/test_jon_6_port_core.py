from __future__ import annotations

import importlib
import sys
from pathlib import Path

from cambc import EntityType, Position


JON_6_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-6"
for module_name in ("builder_bot", "core_bot", "logger", "marker", "utils"):
    sys.modules.pop(module_name, None)
if str(JON_6_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_ROOT))
importlib.invalidate_caches()

import builder_bot as builder_bot_module
import core_bot as core_bot_module
import marker as marker_module
from builder_bot import BuilderBot
from core_bot import CoreBot
from states import BuilderMode


class _StubLogger:
    def log(self, _message: str) -> None:
        return

    def print(self, _message: str) -> None:
        return


class _CoreController:
    def __init__(self, *, round_num: int, titanium: int = 1000) -> None:
        self._round_num = round_num
        self._titanium = titanium
        self._core_pos = Position(10, 10)
        self.spawned_positions: list[Position] = []

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
        return True

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
        if entity_id == 2:
            return EntityType.MARKER
        raise AssertionError(entity_id)

    def get_team(self, _entity_id=None):
        return 1

    def get_marker_value(self, entity_id):
        assert entity_id == 2
        return self._marker_value

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30


def test_opening_assault_spawns_keep_normal_timer_available_on_round_nineteen(
    monkeypatch,
):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())
    monkeypatch.setattr(core_bot_module.random, "shuffle", lambda _items: None)

    bot = CoreBot()
    spawn_records: list[tuple[int, Position]] = []

    for round_num in range(1, 20):
        controller = _CoreController(round_num=round_num)
        bot.run(controller)
        if controller.spawned_positions:
            spawn_records.append((round_num, controller.spawned_positions[0]))

    assert [round_num for round_num, _ in spawn_records] == [1, 2, 3, 4, 5, 6, 19]
    assert spawn_records[4][1] == Position(11, 9)
    assert spawn_records[5][1] == Position(9, 9)
    assert spawn_records[6][1] == Position(11, 11)
    assert bot.assault_spawned == 3


def test_bonus_assault_builder_is_detected_from_spawn_marker(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    marker_value = marker_module.create_assault_spawn_marker(Position(11, 11), 19, 30, 30)
    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(11, 11),
        core_pos=Position(10, 10),
        round_num=19,
        marker_value=marker_value,
    )

    bot._init_turn(controller)

    assert bot.is_assault_role is True
    assert bot.builder_mode == BuilderMode.ASSAULTING
    assert bot.spawn_slot == 2


def test_non_opening_diagonal_without_spawn_marker_stays_economy(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(11, 9),
        core_pos=Position(10, 10),
        round_num=19,
    )

    bot._init_turn(controller)

    assert bot.is_assault_role is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.spawn_slot == 0
