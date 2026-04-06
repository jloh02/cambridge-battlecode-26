from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Position


LEEROY_JONKINS_A8_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "leeroy-jonkins-a8bfs"
)
for module_name in ("mode_tiling_back", "states", "utils", "navigation", "marker"):
    sys.modules.pop(module_name, None)
if str(LEEROY_JONKINS_A8_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(LEEROY_JONKINS_A8_BFS_ROOT))
importlib.invalidate_caches()

import mode_tiling_back  # noqa: E402
from states import BuilderMode, TargetKind  # noqa: E402


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


def test_tiling_back_completion_does_not_emit_connected_harvester_marker(monkeypatch):
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
    assert bot.shared_connected_harvester_positions == set()
    assert calls == []
