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
import timing  # noqa: E402


def teardown_module() -> None:
    for module_name in ("marker", "perception", "timing", "utils"):
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
