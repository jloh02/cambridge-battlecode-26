from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Position


JON_5O_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-5o"
if str(JON_5O_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_ROOT))

import mode_tiling_back
import mode_finding_ore
import navigation
import perception
from states import TargetKind


def test_connected_conveyor_counts_propagate_downstream():
    bot = SimpleNamespace(
        core_pos=Position(5, 5),
        grid={
            (1, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (2, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (3, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (4, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (1, 4): {"building": EntityType.HARVESTER, "building_team": 1},
            (2, 4): {"building": EntityType.HARVESTER, "building_team": 1},
            (3, 4): {"building": EntityType.HARVESTER, "building_team": 1},
            (3, 6): {"building": EntityType.HARVESTER, "building_team": 1},
            (4, 4): {"building": EntityType.HARVESTER, "building_team": 1},
        },
        connected_friendly_conveyors={},
    )

    perception._update_connected_friendly_conveyors(
        bot,
        1,
        {
            (1, 5): Direction.EAST,
            (2, 5): Direction.EAST,
            (3, 5): Direction.EAST,
            (4, 5): Direction.EAST,
        },
        {},
    )

    assert bot.connected_friendly_conveyors == {
        (1, 5): 5,
        (2, 5): 5,
        (3, 5): 5,
        (4, 5): 5,
    }


def test_connected_conveyor_load_uses_downstream_bottleneck_after_merge():
    bot = SimpleNamespace(
        core_pos=Position(5, 5),
        grid={
            (1, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (2, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (3, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (2, 4): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.SOUTH,
            },
            (2, 3): {"building": EntityType.HARVESTER, "building_team": 1},
            (1, 4): {"building": EntityType.HARVESTER, "building_team": 1},
            (1, 6): {"building": EntityType.HARVESTER, "building_team": 1},
            (2, 6): {"building": EntityType.HARVESTER, "building_team": 1},
            (3, 6): {"building": EntityType.HARVESTER, "building_team": 1},
        },
        connected_friendly_conveyors={},
    )

    perception._update_connected_friendly_conveyors(
        bot,
        1,
        {
            (1, 5): Direction.EAST,
            (2, 5): Direction.EAST,
            (3, 5): Direction.EAST,
            (2, 4): Direction.SOUTH,
        },
        {},
    )

    assert bot.connected_friendly_conveyors[(2, 4)] == bot.connected_friendly_conveyors[
        (2, 5)
    ]
    assert bot.connected_friendly_conveyors[(2, 4)] >= 4


def test_nearest_connected_conveyor_prefers_less_loaded_line():
    bot = SimpleNamespace(
        tiled_back_positions=set(),
        connected_friendly_conveyors={
            (3, 5): 5,
            (3, 6): 1,
        },
    )

    target, dist, score = mode_tiling_back._nearest_connected_conveyor(
        bot, Position(3, 5)
    )

    assert target == Position(3, 6)
    assert dist == 1
    assert score == 1.0


def test_connected_conveyor_penalty_stays_flat_through_four_then_jumps():
    assert navigation.connected_conveyor_load_penalty(4) == 0.0
    assert navigation.connected_conveyor_load_penalty(5) > 0.0
    assert (
        navigation.connected_conveyor_load_penalty(10)
        > navigation.connected_conveyor_load_penalty(9)
    )


def test_return_target_prefers_core_when_nearby_line_is_overloaded():
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        connected_friendly_conveyors={(8, 9): 8},
    )

    mode_finding_ore._determine_return_target(bot, Position(8, 8))

    assert bot.return_target_kind == TargetKind.CORE
    assert bot.return_target_pos == Position(9, 9)


def test_connect_to_conveyor_requires_valid_friendly_transport_tile():
    bot = SimpleNamespace(
        pending_build=None,
        connected_friendly_conveyors={(5, 3): 2},
        grid={
            (5, 3): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
            }
        },
    )
    ct = SimpleNamespace(get_team=lambda: 1)

    assert mode_tiling_back._check_connect_to_conveyor(
        bot, ct, Position(5, 3), Position(5, 3), TargetKind.CONVEYOR
    )

    bot.grid[(5, 3)]["building_team"] = 2
    assert not mode_tiling_back._check_connect_to_conveyor(
        bot, ct, Position(5, 3), Position(5, 3), TargetKind.CONVEYOR
    )


def test_compute_pathfinding_step_returns_no_action_when_already_at_target():
    bot = SimpleNamespace(
        pathfinding_state={
            "known_obstacles": set(),
            "path": [("stale", "step")],
            "temporary_obstacles": {},
            "current_target": None,
        },
        grid={},
        builder_mode=None,
        connected_friendly_conveyors={},
        stats={},
    )
    ct = SimpleNamespace(
        get_current_round=lambda: 1,
        get_team=lambda: 1,
    )

    action, state = navigation.compute_pathfinding_step(
        bot,
        ct,
        Position(5, 3),
        Position(5, 3),
        bot.pathfinding_state,
        cardinal_only=True,
    )

    assert action is None
    assert state["path"] == []


def test_conveyor_load_penalty_is_applied_only_when_merging_into_target_line():
    aligned_conveyor = {
        "building": EntityType.CONVEYOR,
        "building_team": 1,
        "building_dir": Direction.EAST,
    }

    non_target_cost = navigation._step_cost(
        aligned_conveyor,
        1.0,
        tiling_back=True,
        move_dir=Direction.EAST,
        my_team=1,
        is_target=False,
        connected_load=8,
    )
    target_cost = navigation._step_cost(
        aligned_conveyor,
        1.0,
        tiling_back=True,
        move_dir=Direction.EAST,
        my_team=1,
        is_target=True,
        connected_load=8,
    )

    assert non_target_cost == 0.1
    assert target_cost > non_target_cost
