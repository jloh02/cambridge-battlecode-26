from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Position


JON_6_A4_BFS_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-6-a4bfsclaude"
for module_name in ("mode_tiling_back", "states", "utils", "navigation", "marker"):
    sys.modules.pop(module_name, None)
if str(JON_6_A4_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A4_BFS_ROOT))
importlib.invalidate_caches()

import mode_tiling_back
from states import BuilderMode, TargetKind


class _StubLogger:
    def log(self, _message: str) -> None:
        return


class _StubController:
    def __init__(self, position: Position) -> None:
        self._position = position

    def get_position(self) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return 20

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30

    def can_place_marker(self, _position: Position) -> bool:
        return True

    def place_marker(self, _position: Position, _value: int) -> None:
        return


def test_tiling_back_completion_does_not_emit_assault_marker(monkeypatch):
    calls: list[tuple[Position, int]] = []

    def _record_marker(_ct, origin_pos, marker_value, directions=None):
        calls.append((origin_pos, marker_value))
        return True

    monkeypatch.setattr(mode_tiling_back.utils, "place_assault_marker_around", _record_marker)

    core_pos = Position(10, 10)
    bot = SimpleNamespace(
        core_pos=core_pos,
        logger=_StubLogger(),
        connected_friendly_conveyors={},
        shared_connected_conveyor_positions=set(),
        shared_connected_harvester_positions=set(),
        last_harvester_pos=Position(15, 15),
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_pos=core_pos,
        return_target_dist_manhatten=0,
        return_target_kind=TargetKind.CORE,
        last_return_target_refresh_round=-1,
        last_connected_refresh_round=-1,
        pending_build=None,
        builder_mode=BuilderMode.TILING_BACK,
    )

    mode_tiling_back.execute(bot, _StubController(core_pos))

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert calls == []


def test_tiling_back_completion_emits_connected_harvester_marker(monkeypatch):
    calls: list[tuple[Position, int]] = []

    def _record_marker(_ct, origin_pos, marker_value, directions=None):
        calls.append((origin_pos, marker_value))
        return True

    monkeypatch.setattr(
        mode_tiling_back.utils,
        "place_connected_harvester_marker_around",
        _record_marker,
    )

    core_pos = Position(10, 10)
    harvester_pos = Position(15, 15)
    bot = SimpleNamespace(
        core_pos=core_pos,
        logger=_StubLogger(),
        connected_friendly_conveyors={},
        shared_connected_conveyor_positions=set(),
        shared_connected_harvester_positions=set(),
        last_harvester_pos=harvester_pos,
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_pos=core_pos,
        return_target_dist_manhatten=0,
        return_target_kind=TargetKind.CORE,
        last_return_target_refresh_round=-1,
        last_connected_refresh_round=-1,
        pending_build=None,
        builder_mode=BuilderMode.TILING_BACK,
    )

    mode_tiling_back.execute(bot, _StubController(core_pos))

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.shared_connected_harvester_positions == {(15, 15)}
    assert len(calls) == 1
    assert calls[0][0] == core_pos
