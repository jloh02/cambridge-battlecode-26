from __future__ import annotations

import importlib
import sys
from pathlib import Path

from cambc import EntityType, Position


LEEROY_JONKINS_A8_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "leeroy-jonkins-a8bfs"
)
for module_name in ("core_bot", "logger", "utils"):
    sys.modules.pop(module_name, None)
if str(LEEROY_JONKINS_A8_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(LEEROY_JONKINS_A8_BFS_ROOT))
importlib.invalidate_caches()

import core_bot as core_bot_module
from core_bot import CoreBot


class _StubLogger:
    def log(self, _message: str) -> None:
        return

    def print(self, _message: str) -> None:
        return


class _StubController:
    def __init__(self, *, round_num: int, titanium: int = 0) -> None:
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


def _is_diagonal_spawn(core_pos: Position, spawn_pos: Position) -> bool:
    return abs(spawn_pos.x - core_pos.x) == 1 and abs(spawn_pos.y - core_pos.y) == 1


def test_opening_assault_wave_spawns_on_rounds_four_through_seven(monkeypatch):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())
    monkeypatch.setattr(core_bot_module.random, "shuffle", lambda _items: None)

    bot = CoreBot()
    spawn_records: list[tuple[int, Position]] = []

    for round_num in range(0, 8):
        controller = _StubController(round_num=round_num)
        bot.run(controller)
        if controller.spawned_positions:
            spawn_records.append((round_num, controller.spawned_positions[0]))

    assert [round_num for round_num, _ in spawn_records] == list(range(0, 8))
    assert all(
        not _is_diagonal_spawn(Position(10, 10), spawn_pos)
        for _, spawn_pos in spawn_records[:4]
    )
    assert all(
        _is_diagonal_spawn(Position(10, 10), spawn_pos)
        for _, spawn_pos in spawn_records[4:8]
    )
    assert bot.assault_spawned == 4


def test_low_resource_assault_quota_matches_four_round_opening_wave(monkeypatch):
    monkeypatch.setattr(core_bot_module.logger, "Logger", lambda _ct: _StubLogger())

    bot = CoreBot()
    controller = _StubController(round_num=4, titanium=0)

    assert bot._assault_quota(controller) == 4


def test_max_builder_count_is_twenty(monkeypatch):
    assert core_bot_module.MAX_BUILDER_COUNT == 20
