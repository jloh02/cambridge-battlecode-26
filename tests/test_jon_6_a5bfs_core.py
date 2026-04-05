from __future__ import annotations

import importlib
import sys
from pathlib import Path

from cambc import EntityType, Position


JON_6_A5_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a5bfs"
)
for module_name in ("builder_bot", "core_bot", "logger", "utils"):
    sys.modules.pop(module_name, None)
if str(JON_6_A5_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A5_BFS_ROOT))
importlib.invalidate_caches()

import builder_bot as builder_bot_module
import core_bot as core_bot_module
from builder_bot import BuilderBot
from core_bot import CoreBot


class _StubLogger:
    def log(self, _message: str) -> None:
        return

    def print(self, _message: str) -> None:
        return


class _StubController:
    def __init__(self, *, round_num: int, titanium: int = 1000) -> None:
        self._round_num = round_num
        self._titanium = titanium
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


class _BuilderInitController:
    def __init__(
        self,
        *,
        position: Position,
        core_pos: Position,
        round_num: int,
    ) -> None:
        self._position = position
        self._core_pos = core_pos
        self._round_num = round_num
        self._entity_id = 7

    def get_position(self, entity_id=None) -> Position:
        if entity_id is None:
            return self._position
        return self._core_pos

    def get_current_round(self) -> int:
        return self._round_num

    def get_nearby_entities(self):
        return [1]

    def get_entity_type(self, entity_id):
        if entity_id is None:
            return EntityType.BUILDER_BOT
        assert entity_id == 1
        return EntityType.CORE

    def get_id(self) -> int:
        return self._entity_id

    def get_team(self, _entity_id=None):
        return 1

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30

    def can_move(self, _direction) -> bool:
        return True

    def move(self, direction) -> None:
        self._position = self._position.add(direction)


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


def test_assault_spawns_do_not_place_spawn_markers(monkeypatch):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())
    monkeypatch.setattr(core_bot_module.random, "shuffle", lambda _items: None)
    monkeypatch.setattr(
        core_bot_module.utils,
        "place_assault_marker_around",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("assault spawn markers should not be placed")
        ),
    )

    bot = CoreBot()
    spawn_rounds: list[int] = []

    for round_num in range(1, 20):
        controller = _StubController(round_num=round_num)
        bot.run(controller)
        if controller.spawned_positions:
            spawn_rounds.append(round_num)

    assert spawn_rounds == [1, 2, 3, 4, 5, 6, 19]
    assert bot.assault_spawned == 3


def test_diagonal_assault_builder_uses_fast_perception_during_opening_escape(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(11, 9),
        core_pos=Position(10, 10),
        round_num=19,
    )

    bot._init_turn(controller)

    assert bot.is_assault_role is True
    assert bot.last_full_perception_round == -1
    assert bot._should_use_fast_perception(controller) is True


def test_opening_escape_turn_skips_perception_scan(monkeypatch):
    monkeypatch.setattr(builder_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = BuilderBot()
    controller = _BuilderInitController(
        position=Position(11, 9),
        core_pos=Position(10, 10),
        round_num=19,
    )

    monkeypatch.setattr(
        builder_bot_module.perception,
        "scan_around",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("opening escape turn should skip perception")
        ),
    )

    bot.run(controller)

    assert controller.get_position() != Position(11, 9)
