from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cambc import Position


DUCK_1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "duck-1"
if str(DUCK_1_ROOT) not in sys.path:
    sys.path.insert(0, str(DUCK_1_ROOT))

import mode_exploring  # noqa: E402
import mode_finding_ore  # noqa: E402
from states import BuilderMode, TargetKind  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _cleanup_duck1_modules():
    yield
    for module_name in (
        "marker",
        "mode_exploring",
        "mode_finding_ore",
        "navigation",
        "states",
        "utils",
    ):
        sys.modules.pop(module_name, None)
    while str(DUCK_1_ROOT) in sys.path:
        sys.path.remove(str(DUCK_1_ROOT))


class _StubLogger:
    def log(self, _message: str) -> None:
        return


class _StubController:
    def __init__(
        self,
        *,
        position: Position,
        round_num: int = 100,
        can_build_harvester: bool = False,
    ) -> None:
        self._position = position
        self._round = round_num
        self._can_build_harvester = can_build_harvester
        self.built_harvesters: list[Position] = []

    def get_position(self) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return self._round

    def advance_round(self) -> None:
        self._round += 1

    def get_team(self):
        return 1

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30

    def can_build_harvester(self, _position: Position) -> bool:
        return self._can_build_harvester

    def build_harvester(self, position: Position) -> None:
        self.built_harvesters.append(position)

    def get_global_resources(self) -> tuple[int, int]:
        return (0, 0)

    def get_harvester_cost(self) -> tuple[int, int]:
        return (100, 0)


def _ore_mode_bot(*ore_positions: Position) -> SimpleNamespace:
    return SimpleNamespace(
        logger=_StubLogger(),
        builder_mode=BuilderMode.FINDING_ORE,
        core_pos=Position(10, 10),
        last_harvester_pos=None,
        last_harvester_round=-1,
        last_lane_survey_round=-1,
        survey_repair_target_pos=None,
        connected_friendly_conveyors={},
        known_harvesters={},
        titanium_locations=set(ore_positions),
        axionite_locations=set(),
        bot_locations=set(),
        claimed_harvesters=set(),
        shared_ore_positions=set(),
        blocked_ore_targets={},
        ore_build_fail_ore=None,
        ore_build_fail_count=0,
        grid={},
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "current_target": None,
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
            "tiling_back_wait_turns": 0,
        },
        foundry_anchor_pos=None,
        return_foundry_pos=None,
        foundry_bootstrap_builds_remaining=0,
        last_foundry_attempt_round=-9999,
        axionite_probe_builds=0,
        last_axionite_probe_round=-9999,
        tiled_back_positions=set(),
        pending_build=None,
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_pos=None,
        return_target_dist_manhatten=float("inf"),
        return_target_kind=TargetKind.CORE,
        last_return_target_refresh_round=-1,
        explore_target_chunk=None,
        explore_target_pos=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
    )


def test_repeated_failed_harvester_build_blocks_ore_target(monkeypatch):
    ore_pos = Position(6, 6)
    bot = _ore_mode_bot(ore_pos)
    ct = _StubController(position=Position(6, 5), round_num=100, can_build_harvester=False)
    explore_calls: list[int] = []

    monkeypatch.setattr(mode_finding_ore, "_share_ore_marker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mode_exploring,
        "execute",
        lambda _bot, _ct: explore_calls.append(_ct.get_current_round()),
    )

    for _ in range(mode_finding_ore.ORE_BUILD_FAIL_THRESHOLD):
        mode_finding_ore.execute(bot, ct)
        ct.advance_round()

    ore_key = (ore_pos.x, ore_pos.y)
    assert ore_key in bot.blocked_ore_targets
    assert bot.blocked_ore_targets[ore_key] > ct.get_current_round()
    assert bot.ore_build_fail_ore is None
    assert bot.ore_build_fail_count == 0

    mode_finding_ore.execute(bot, ct)

    assert bot.builder_mode == BuilderMode.EXPLORING
    assert explore_calls == [ct.get_current_round()]


def test_successful_harvester_build_clears_blocked_ore_state(monkeypatch):
    ore_pos = Position(8, 8)
    bot = _ore_mode_bot(ore_pos)
    ore_key = (ore_pos.x, ore_pos.y)
    # Simulate a just-expired cooldown so the ore is selectable again this turn.
    bot.blocked_ore_targets[ore_key] = 219
    bot.ore_build_fail_ore = ore_key
    bot.ore_build_fail_count = 2
    ct = _StubController(position=Position(8, 7), round_num=220, can_build_harvester=True)

    monkeypatch.setattr(mode_finding_ore, "_share_ore_marker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mode_finding_ore,
        "_enter_tiling_back_mode",
        lambda b, _ore: setattr(b, "builder_mode", BuilderMode.TILING_BACK),
    )

    mode_finding_ore.execute(bot, ct)

    assert ct.built_harvesters == [ore_pos]
    assert ore_key not in bot.blocked_ore_targets
    assert bot.ore_build_fail_ore is None
    assert bot.ore_build_fail_count == 0
    assert bot.builder_mode == BuilderMode.TILING_BACK


def test_blocked_ore_is_skipped_when_selecting_best_target():
    blocked_ore = Position(1, 0)
    open_ore = Position(3, 0)
    bot = _ore_mode_bot(blocked_ore, open_ore)
    bot.blocked_ore_targets[(blocked_ore.x, blocked_ore.y)] = 200
    ct = _StubController(position=Position(0, 0), round_num=100, can_build_harvester=False)

    target = mode_finding_ore._find_best_ore_target(bot, ct, max_bfs_nodes=20)

    assert target is not None
    assert target[0] == open_ore
