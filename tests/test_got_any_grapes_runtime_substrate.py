from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Position


BOT_ROOT = Path(__file__).resolve().parent.parent / "bots" / "got-any-grapes"
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

import marker  # noqa: E402
import perception  # noqa: E402
import mode_finding_ore  # noqa: E402
from builder_bot import BuilderBot  # noqa: E402
from states import BuilderMode, TargetKind  # noqa: E402
import timing  # noqa: E402


def teardown_module() -> None:
    for module_name in (
        "marker",
        "perception",
        "mode_finding_ore",
        "builder_bot",
        "states",
        "timing",
        "utils",
    ):
        sys.modules.pop(module_name, None)
    while str(BOT_ROOT) in sys.path:
        sys.path.remove(str(BOT_ROOT))


def test_marker_decode_accepts_legacy_and_reference_schemas():
    ore_value = (
        (((Position(7, 9).x << max(1, (40 - 1).bit_length())) | Position(7, 9).y) << marker.ROUND_BITS)
    )
    ore_value = ((ore_value | 123) << marker.TYPE_BITS) | marker.MarkerType.ORE_LOCATION.value
    ore_record = marker.decode_marker(ore_value, map_width=40, map_height=40)
    assert ore_record is not None
    assert ore_record.kind == marker.MarkerType.ORE_LOCATION
    assert ore_record.position == Position(7, 9)


def test_world_orientation_marker_round_trips():
    value = marker.create_world_orientation_marker(
        symmetry=marker.SymmetryType.ROTATIONAL,
        confidence=11,
        rejected_mask=0b101,
        salient_flags=0b10010,
        current_round=222,
    )
    record = marker.decode_marker(value)
    assert record is not None
    assert record.symmetry == marker.SymmetryType.ROTATIONAL
    assert record.confidence == 11
    assert record.rejected_mask == 0b101
    assert record.salient_flags == 0b10010


def test_assault_claim_marker_round_trips():
    value = marker.create_assault_claim_marker(
        Position(12, 7),
        owner_tag=marker.assault_claim_owner_tag(45),
        current_round=91,
        map_width=40,
        map_height=40,
    )
    parsed = marker.parse_assault_claim_marker(value, 40, 40)
    assert parsed == (Position(12, 7), marker.assault_claim_owner_tag(45), 91)


class _MarkerController:
    def __init__(self, marker_value: int) -> None:
        self._marker_value = marker_value

    def get_id(self) -> int:
        return 7

    def get_map_width(self) -> int:
        return 40

    def get_map_height(self) -> int:
        return 40

    def get_current_round(self) -> int:
        return 200

    def get_team(self, entity_id=None):
        return 1

    def get_marker_value(self, entity_id: int) -> int:
        assert entity_id == 1
        return self._marker_value


def test_perception_scans_world_orientation_marker():
    controller = _MarkerController(
        marker.create_world_orientation_marker(
            symmetry=marker.SymmetryType.HORIZONTAL,
            confidence=9,
            rejected_mask=0b010,
            salient_flags=0b00101,
            current_round=198,
        )
    )
    bot = SimpleNamespace(
        claimed_explore_chunks=set(),
        claimed_assault_anchor_keys=set(),
        exploration_frontier_chunks=set(),
        offensive_route_directions=set(),
        titanium_locations=set(),
        shared_connected_harvester_positions=set(),
        pathfinding_state={"known_obstacles": set()},
        known_friendly_conveyors=set(),
        connected_friendly_conveyors={},
        world_orientation=None,
    )
    perception._scan_nearby_markers(  # noqa: SLF001
        bot,
        controller,
        nearby_buildings=[1],
        nearby_cache={1: {"type": EntityType.MARKER, "team": 1}},
    )
    assert bot.world_orientation is not None
    assert bot.world_orientation["symmetry"] == marker.SymmetryType.HORIZONTAL
    assert bot.world_orientation["confidence"] == 9


def test_timing_governor_uses_trusted_wave_1_8ms_budget():
    governor = timing.TimingGovernor.start_turn(1_000_000)
    assert governor.soft_deadline_ns == 2_800_000
    assert governor.hard_deadline_ns == 2_800_000
    assert governor.should_skip_low_priority(2_690_000) is True
    assert governor.is_hard_expired(2_800_001) is True


def test_enter_tiling_back_from_origin_sets_hijack_origin_without_touching_harvester():
    bot = SimpleNamespace(
        last_harvester_pos=Position(2, 2),
        tiled_back_positions={(9, 9)},
        nearest_conveyor_pos=Position(1, 1),
        nearest_conveyor_dist_manhatten=3,
        return_target_pos=Position(3, 3),
        return_target_dist_manhatten=4,
        return_target_kind=TargetKind.CONVEYOR,
        last_return_target_refresh_round=8,
        pathfinding_state={
            "path": [Position(4, 4)],
            "temporary_obstacles": {(5, 5): 1},
            "tiling_back_wait_turns": 2,
            "last_replan_signature": "x",
            "last_replan_round": 7,
        },
        explore_target_chunk=(1, 1),
        explore_target_pos=Position(6, 6),
        pending_bridge_plan=("bridge",),
        pending_build=("build",),
        bridge_transit_path=[Position(7, 7)],
        bridge_transit_cooldown_until=99,
        connected_friendly_conveyors={(10, 10): 1},
        core_pos=Position(0, 0),
        builder_mode=BuilderMode.EXPLORING,
    )
    mode_finding_ore.enter_tiling_back_from_origin(
        bot,
        Position(10, 10),
        origin_kind="HIJACK",
    )
    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.tiling_back_origin_kind == "HIJACK"
    assert bot.last_harvester_pos == Position(2, 2)
    assert bot.tiled_back_positions == set()
    assert bot.pending_build is None
    assert bot.return_target_pos == Position(10, 10)
    assert bot.return_target_kind == TargetKind.CONVEYOR


def test_builder_bot_switches_to_hijacking_when_visible_target_exists(monkeypatch):
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    expected_target = (Position(8, 8), Position(8, 9))

    import mode_hijacking  # noqa: E402

    monkeypatch.setattr(
        mode_hijacking,
        "find_visible_hijack_target",
        lambda _bot, _ct: expected_target,
    )
    changed = bot._maybe_switch_to_hijack(SimpleNamespace())
    assert changed is True
    assert bot.builder_mode == BuilderMode.HIJACKING
    assert bot.hijack_source_pos == expected_target[0]
    assert bot.hijack_entry_pos == expected_target[1]
