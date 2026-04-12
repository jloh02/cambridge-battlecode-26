from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


BOT_ROOT = Path(__file__).resolve().parent.parent / "bots" / "got-any-grapes"
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

import marker  # noqa: E402
import perception  # noqa: E402
import mode_finding_ore  # noqa: E402
import mode_assaulting  # noqa: E402
import assault  # noqa: E402
import mode_hijacking  # noqa: E402
import mode_tiling_back  # noqa: E402
import navigation  # noqa: E402
import defense  # noqa: E402
import utils  # noqa: E402
from builder_bot import BuilderBot  # noqa: E402
from sentinel_bot import SentinelBot  # noqa: E402
from states import ActionType, BuilderMode, TargetKind  # noqa: E402
import timing  # noqa: E402


def teardown_module() -> None:
    for module_name in (
        "marker",
        "perception",
        "mode_finding_ore",
        "mode_assaulting",
        "defense",
        "builder_bot",
        "sentinel_bot",
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


def test_assault_site_prefers_core_hitting_arc_on_same_ring():
    harvester_pos = Position(10, 10)
    core_pos = Position(4, 9)
    enemies = [
        assault.VisibleEnemy(harvester_pos, EntityType.HARVESTER),
        assault.VisibleEnemy(core_pos, EntityType.CORE),
    ]

    site = assault.choose_best_site_for_harvester(
        harvester_position=harvester_pos,
        current_position=Position(7, 10),
        enemies=enemies,
        map_width=30,
        map_height=30,
        enemy_core_center=core_pos,
        current_anchor=harvester_pos,
    )

    assert site is not None
    assert site.ring_position == Position(9, 10)
    assert site.sentinel_direction == Direction.WEST
    assert site.hits_core_center is True
    assert site.target.entity_type == EntityType.CORE


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


def test_pipeline_claim_marker_round_trips_and_decodes():
    value = marker.create_pipeline_claim_marker(
        Position(13, 8),
        current_round=91,
        map_width=40,
        map_height=40,
    )

    parsed = marker.parse_pipeline_claim_marker(value, 40, 40)
    decoded = marker.decode_marker(value, map_width=40, map_height=40)

    assert parsed == (Position(13, 8), 91)
    assert decoded.kind == marker.MarkerType.PIPELINE_CLAIM
    assert decoded.position == Position(13, 8)
    assert decoded.round_mod == 91


class _GotAnyGrapesSentinelController:
    def __init__(self, *, legal_targets: set[tuple[int, int]] | None = None) -> None:
        self.self_team = 1
        self.self_position = Position(5, 5)
        self.entities = {
            11: {
                "team": 2,
                "type": EntityType.HARVESTER,
                "position": Position(5, 4),
                "hp": 50,
            },
            12: {
                "team": 2,
                "type": EntityType.CONVEYOR,
                "position": Position(6, 4),
                "hp": 15,
            },
            13: {
                "team": 2,
                "type": EntityType.SENTINEL,
                "position": Position(7, 5),
                "hp": 40,
            },
            14: {
                "team": 2,
                "type": EntityType.CORE,
                "position": Position(8, 5),
                "hp": 200,
            },
            15: {
                "team": 2,
                "type": EntityType.BUILDER_BOT,
                "position": Position(6, 5),
                "hp": 40,
            },
        }
        self.legal_targets = legal_targets or {
            (data["position"].x, data["position"].y) for data in self.entities.values()
        }
        self.fired_at: Position | None = None

    def get_entity_type(self, entity_id=None):
        if entity_id is None:
            return EntityType.SENTINEL
        return self.entities[entity_id]["type"]

    def get_nearby_entities(self):
        return list(self.entities)

    def get_team(self, entity_id=None):
        if entity_id is None:
            return self.self_team
        return self.entities[entity_id]["team"]

    def get_position(self, entity_id=None):
        if entity_id is None:
            return self.self_position
        return self.entities[entity_id]["position"]

    def get_hp(self, entity_id):
        return self.entities[entity_id]["hp"]

    def get_tile_env(self, position: Position):
        if position == Position(5, 4):
            return Environment.ORE_TITANIUM
        return Environment.EMPTY

    def can_fire(self, position: Position):
        return (position.x, position.y) in self.legal_targets

    def fire(self, position: Position):
        self.fired_at = position


def test_sentinel_prioritizes_enemy_builder_before_gun_and_logistics():
    controller = _GotAnyGrapesSentinelController()
    del controller.entities[11]
    controller.entities[31] = {
        "team": 1,
        "type": EntityType.CORE,
        "position": Position(5, 6),
        "hp": 200,
    }

    SentinelBot().run(controller)

    assert controller.fired_at == Position(6, 5)


def test_sentinel_keeps_hijack_anchor_pressure_before_builder():
    controller = _GotAnyGrapesSentinelController()

    SentinelBot().run(controller)

    assert controller.fired_at == Position(7, 5)


def test_sentinel_targets_gun_before_logistics_when_no_builder_is_legal():
    controller = _GotAnyGrapesSentinelController()
    del controller.entities[15]

    SentinelBot().run(controller)

    assert controller.fired_at == Position(7, 5)


def test_sentinel_skips_enemy_tile_occupied_by_friendly_builder():
    controller = _GotAnyGrapesSentinelController()
    del controller.entities[11]
    controller.entities[31] = {
        "team": 1,
        "type": EntityType.CORE,
        "position": Position(5, 6),
        "hp": 200,
    }
    controller.entities[21] = {
        "team": 1,
        "type": EntityType.BUILDER_BOT,
        "position": Position(6, 5),
        "hp": 10,
    }

    SentinelBot().run(controller)

    assert controller.fired_at == Position(7, 5)


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
        claimed_pipeline_positions=set(),
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


def test_perception_marker_dispatch_skips_unrelated_parsers(monkeypatch):
    controller = _MarkerController(
        marker.create_ore_marker(
            Position(6, 6),
            current_round=198,
            map_width=40,
            map_height=40,
        )
    )
    bot = SimpleNamespace(
        claimed_explore_chunks=set(),
        claimed_assault_anchor_keys=set(),
        claimed_pipeline_positions=set(),
        exploration_frontier_chunks=set(),
        offensive_route_directions=set(),
        titanium_locations=set(),
        shared_connected_harvester_positions=set(),
        pathfinding_state={"known_obstacles": set()},
        known_friendly_conveyors=set(),
        connected_friendly_conveyors={},
        world_orientation=None,
    )

    monkeypatch.setattr(
        marker,
        "parse_assault_claim_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ore markers should not call assault parser")
        ),
    )

    perception._scan_nearby_markers(  # noqa: SLF001
        bot,
        controller,
        nearby_buildings=[1],
        nearby_cache={1: {"type": EntityType.MARKER, "team": 1}},
    )

    assert Position(6, 6) in bot.titanium_locations


def test_perception_scans_pipeline_claim_marker():
    controller = _MarkerController(
        marker.create_pipeline_claim_marker(
            Position(11, 9),
            current_round=198,
            map_width=40,
            map_height=40,
        )
    )
    bot = SimpleNamespace(
        claimed_explore_chunks=set(),
        claimed_assault_anchor_keys=set(),
        claimed_pipeline_positions=set(),
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

    assert bot.claimed_pipeline_positions == {(11, 9)}
    assert bot.connected_friendly_conveyors == {}


def test_perception_only_reads_building_health_for_friendly_buildings():
    hp_reads = []

    class _SnapshotController:
        def get_tile_building_id(self, pos):
            return {(0, 0): 1, (1, 0): 2}.get((pos.x, pos.y))

        def get_entity_type(self, entity_id):
            return EntityType.CORE

        def get_team(self, entity_id=None):
            if entity_id is None:
                return 1
            return {1: 1, 2: 2}[entity_id]

        def get_hp(self, entity_id):
            hp_reads.append(("hp", entity_id))
            return 100

        def get_max_hp(self, entity_id):
            hp_reads.append(("max_hp", entity_id))
            return 200

        def get_nearby_units(self):
            return []

        def get_tile_env(self, pos):
            return None

    _, nearby_buildings, _, nearby_cache = perception._collect_visible_snapshot(  # noqa: SLF001
        SimpleNamespace(grid={}),
        _SnapshotController(),
        [Position(0, 0), Position(1, 0)],
        include_building_health=True,
    )

    assert nearby_buildings == [1, 2]
    assert hp_reads == [("hp", 1), ("max_hp", 1)]
    assert nearby_cache[1]["hp"] == 100
    assert "hp" not in nearby_cache[2]


def test_perception_snapshot_skips_tile_env_for_cached_wall_empty():
    env_reads = []
    tile_builder_reads = []

    class _CachedEnvController:
        def get_team(self, entity_id=None):
            return 1

        def get_tile_env(self, pos):
            env_reads.append((pos.x, pos.y))
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            return None

        def get_tile_builder_bot_id(self, pos):
            tile_builder_reads.append((pos.x, pos.y))
            return None

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            return EntityType.CORE

    bot = SimpleNamespace(
        grid={
            (0, 0): {"env": Environment.EMPTY, "last_seen": 3},
            (1, 0): {"env": Environment.WALL, "last_seen": 3},
            (2, 0): {"env": Environment.ORE_TITANIUM, "last_seen": 3},
            # (3, 0) has no cache entry so env must be queried
        },
    )

    visible_tiles, _, _, _ = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        _CachedEnvController(),
        [Position(0, 0), Position(1, 0), Position(2, 0), Position(3, 0)],
        include_building_health=True,
    )

    # EMPTY and WALL are static → cached; ORE_TITANIUM can deplete so it must
    # be re-queried. Unknown tiles also must be queried.
    assert (0, 0) not in env_reads
    assert (1, 0) not in env_reads
    assert (2, 0) in env_reads
    assert (3, 0) in env_reads
    # Per-tile builder-bot lookup must not fire for the new full-scan path —
    # builders come from get_nearby_units() instead.
    assert tile_builder_reads == []
    # Visible tile env reflects the cached envs.
    env_by_pos = {(p.x, p.y): env for p, env, _, _ in visible_tiles}
    assert env_by_pos[(0, 0)] is Environment.EMPTY
    assert env_by_pos[(1, 0)] is Environment.WALL
    assert env_by_pos[(2, 0)] is Environment.EMPTY  # from _CachedEnvController
    # Every tuple reports builder_bot_id=None now.
    assert all(entry[3] is None for entry in visible_tiles)


def test_perception_snapshot_defers_cached_tiles_when_time_pressured():
    """Resumable anytime semantics: when the hard budget is exhausted mid
    scan, tiles that already have cached grid data are DEFERRED (no SDK
    calls, not added to visible_tiles) but their positions are recorded
    in bot._snapshot_deferred_positions so downstream code can merge them
    into visible_positions. Nothing is dropped — scanned tiles get fresh
    data, deferred tiles re-use their last good grid snapshot, and next
    turn the staleness ordering puts the deferred ones first so they get
    refreshed then."""
    sdk_env_calls = []
    sdk_building_calls = []

    class _DeferringController:
        def get_team(self, entity_id=None):
            return 1

        def get_tile_env(self, pos):
            sdk_env_calls.append((pos.x, pos.y))
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            sdk_building_calls.append((pos.x, pos.y))
            return None

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            return EntityType.CORE

    nearby = [Position(i, 0) for i in range(100)]
    # Every tile already has cached grid data with a recent last_seen, so
    # the cheap hydration path can activate for budget-exhausted tiles.
    grid = {
        (i, 0): {
            "env": Environment.EMPTY,
            "last_seen": 5,
        }
        for i in range(100)
    }

    governor = timing.TimingGovernor.start_turn(0)
    bot = SimpleNamespace(
        grid=grid,
        timing_governor=governor,
        turn_hard_deadline_ns=0,  # "now" exceeds deadline → gate fires asap
    )

    visible_tiles, _, _, _ = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        _DeferringController(),
        nearby,
        include_building_health=False,
    )

    deferred = getattr(bot, "_snapshot_deferred_positions", None)
    assert deferred is not None and len(deferred) > 0, (
        "budget exhaustion should produce deferred positions"
    )
    # Deferred tiles do NOT appear in visible_tiles (their grid data stays
    # untouched and last_seen is not refreshed), but every nearby tile is
    # accounted for across scanned + deferred.
    visible_tiles_positions = {(p.x, p.y) for p, _, _, _ in visible_tiles}
    assert not (deferred & visible_tiles_positions)
    assert len(visible_tiles) + len(deferred) == 100
    # SDK calls only fire for actually-scanned tiles.
    assert len(sdk_building_calls) == len(visible_tiles)


def test_perception_snapshot_does_not_truncate_with_plenty_of_time():
    """Inverse of the truncation test: when the governor has ample time left,
    the snapshot loop must process every tile so behavior on fast hardware
    is unchanged."""
    sdk_calls = {"env": 0}

    class _FullScanController:
        def get_team(self, entity_id=None):
            return 1

        def get_tile_env(self, pos):
            sdk_calls["env"] += 1
            return Environment.ORE_TITANIUM  # bypass static cache

        def get_tile_building_id(self, pos):
            return None

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            return EntityType.CORE

    nearby = [Position(i, 0) for i in range(60)]
    # Governor with a deadline 10 seconds in the future from NOW → always
    # plenty of budget. turn_hard_deadline_ns is wall-clock-relative (ns
    # since epoch), so we anchor to time.time_ns() rather than to 0.
    import time as _t
    future_deadline_ns = _t.time_ns() + 10_000_000_000
    governor = timing.TimingGovernor(
        started_ns=_t.time_ns(),
        soft_deadline_ns=future_deadline_ns,
        hard_deadline_ns=future_deadline_ns,
    )
    bot = SimpleNamespace(
        grid={},
        timing_governor=governor,
        turn_hard_deadline_ns=future_deadline_ns,
    )

    visible_tiles, _, _, _ = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        _FullScanController(),
        nearby,
        include_building_health=False,
    )

    assert len(visible_tiles) == 60
    assert sdk_calls["env"] == 60


def test_perception_snapshot_reuses_cached_building_metadata():
    """When get_tile_building_id returns the same id that we already stored
    for that tile on a previous full scan, _collect_visible_snapshot hydrates
    type/team/direction from the cached grid entry and avoids the 2-4 SDK
    calls for get_entity_type/get_team/get_direction. Only HP is re-queried."""
    calls = {"type": 0, "team": 0, "direction": 0, "hp": 0, "max_hp": 0}

    class _IdCacheController:
        def get_team(self, entity_id=None):
            if entity_id is None:
                return 1
            calls["team"] += 1
            return 1

        def get_tile_env(self, pos):
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            return 42  # same id as cached

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            calls["type"] += 1
            return EntityType.CONVEYOR

        def get_direction(self, entity_id):
            calls["direction"] += 1
            return Direction.EAST

        def get_hp(self, entity_id):
            calls["hp"] += 1
            return 20

        def get_max_hp(self, entity_id):
            calls["max_hp"] += 1
            return 20

    bot = SimpleNamespace(
        grid={
            (0, 0): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_id": 42,
                "building_dir": Direction.EAST,
            }
        }
    )

    _, nearby_buildings, _, nearby_cache = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        _IdCacheController(),
        [Position(0, 0)],
        include_building_health=True,
    )

    assert nearby_buildings == [42]
    assert calls["type"] == 0
    assert calls["direction"] == 0
    assert calls["hp"] == 1
    assert calls["max_hp"] == 1
    assert nearby_cache[42]["type"] is EntityType.CONVEYOR
    assert nearby_cache[42]["team"] == 1
    assert nearby_cache[42]["direction"] is Direction.EAST
    assert nearby_cache[42]["hp"] == 20


def test_perception_snapshot_falls_back_to_sdk_when_building_id_changed():
    """If get_tile_building_id returns a NEW id at a tile (e.g. the old
    building was destroyed and a new one built), we must fall through to
    the SDK path and re-query the new building's metadata."""
    calls = {"type": 0, "direction": 0}

    class _NewBuildingController:
        def get_team(self, entity_id=None):
            return 1

        def get_tile_env(self, pos):
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            return 99  # different from cached id=42

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            calls["type"] += 1
            return EntityType.HARVESTER

        def get_direction(self, entity_id):
            calls["direction"] += 1
            return Direction.EAST

        def get_hp(self, entity_id):
            return 30

        def get_max_hp(self, entity_id):
            return 30

    bot = SimpleNamespace(
        grid={
            (0, 0): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_id": 42,
                "building_dir": Direction.WEST,
            }
        }
    )

    _, _, _, nearby_cache = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        _NewBuildingController(),
        [Position(0, 0)],
        include_building_health=False,
    )

    assert calls["type"] == 1
    assert calls["direction"] == 0
    assert nearby_cache[99]["type"] is EntityType.HARVESTER


def test_perception_snapshot_builders_come_from_get_nearby_units():
    class _UnitController:
        def get_team(self, entity_id=None):
            if entity_id is None:
                return 1
            return {101: 1, 102: 2}[entity_id]

        def get_tile_env(self, pos):
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            return None

        def get_tile_builder_bot_id(self, pos):
            raise AssertionError(
                "full scan must not call get_tile_builder_bot_id per tile"
            )

        def get_nearby_units(self):
            return [101, 102]

        def get_entity_type(self, entity_id):
            return EntityType.BUILDER_BOT

        def get_position(self, entity_id=None):
            return {101: Position(0, 0), 102: Position(1, 0)}[entity_id]

    bot = SimpleNamespace(grid={})
    _, _, nearby_units, nearby_cache = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        _UnitController(),
        [Position(0, 0), Position(1, 0)],
        include_building_health=False,
    )

    assert 101 in nearby_units
    assert 102 in nearby_units
    assert nearby_cache[101]["type"] == EntityType.BUILDER_BOT
    assert nearby_cache[101]["team"] == 1
    assert nearby_cache[102]["team"] == 2


def test_timing_governor_has_budget_for_gates_phases():
    governor = timing.TimingGovernor.start_turn(0)
    # Pretend "now" is 0 → the full hard budget is still available.
    assert governor.has_budget_for(timing.MODE_ENTRY_NS, now_ns=0) is True
    assert governor.has_budget_for(timing.PERCEPTION_OPTIONAL_NS, now_ns=0) is True
    assert governor.has_budget_for(timing.LOOKAHEAD_BUILD_NS, now_ns=0) is True
    # Pretend "now" is very close to the hard deadline.
    close_to_deadline = governor.hard_deadline_ns - 100_000
    assert governor.has_budget_for(timing.MODE_ENTRY_NS, now_ns=close_to_deadline) is False
    assert governor.has_budget_for(timing.LOOKAHEAD_BUILD_NS, now_ns=close_to_deadline) is False
    assert governor.has_budget_for(timing.PERCEPTION_OPTIONAL_NS, now_ns=close_to_deadline) is False
    # Just past the deadline → nothing is affordable, but the call does not raise.
    assert governor.has_budget_for(1, now_ns=governor.hard_deadline_ns + 1) is False


def test_perception_tracks_known_env_count_incrementally():
    bot = SimpleNamespace(
        grid={},
        tracked_harvesters={},
        grid_env_known_count=0,
    )
    controller = SimpleNamespace(get_current_round=lambda: 7)

    perception._update_master_grid(  # noqa: SLF001
        bot,
        controller,
        [(Position(1, 1), Environment.EMPTY, None, None)],
        nearby_units=[],
        nearby_cache={},
    )
    assert bot.grid_env_known_count == 1

    perception._update_master_grid(  # noqa: SLF001
        bot,
        controller,
        [(Position(1, 1), Environment.EMPTY, None, None)],
        nearby_units=[],
        nearby_cache={},
    )
    assert bot.grid_env_known_count == 1

    perception._update_master_grid(  # noqa: SLF001
        bot,
        controller,
        [(Position(2, 1), Environment.ORE_TITANIUM, None, None)],
        nearby_units=[],
        nearby_cache={},
    )
    assert bot.grid_env_known_count == 2


def test_assault_symmetry_uses_incremental_env_count(monkeypatch):
    values_called = {"count": 0}

    class _Grid(dict):
        def values(self):
            values_called["count"] += 1
            return super().values()

    bot = BuilderBot()
    bot.grid = _Grid(
        {
            (1, 1): {"env": Environment.EMPTY, "last_seen": 3},
            (2, 1): {"env": Environment.WALL, "last_seen": 3},
        }
    )
    bot.grid_env_known_count = 2
    bot.core_pos = Position(0, 0)
    bot.last_symmetry_update_round = -9999
    bot.last_enemy_core_position = None
    bot.world_orientation = None
    bot.best_symmetry_mode = None
    bot.symmetry_candidates = ("ROT180", "MIRROR_X", "MIRROR_Y")
    bot.confirmed_enemy_harvesters = {}
    bot.titanium_locations = set()
    bot.harvester_anchor = None
    bot.visible_enemy_targets = []
    bot.visible_positions = set()

    monkeypatch.setattr(
        assault,
        "build_symmetry_informative_tiles",
        lambda **_kwargs: (),
    )
    monkeypatch.setattr(
        assault,
        "evaluate_symmetry_modes",
        lambda **_kwargs: (("ROT180",), "ROT180", "HIGH", ()),
    )
    monkeypatch.setattr(
        assault,
        "build_predicted_enemy_harvesters",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        mode_assaulting,
        "_publish_world_orientation",
        lambda *_args, **_kwargs: None,
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 24,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_position=lambda: Position(1, 1),
        get_team=lambda: 1,
    )

    mode_assaulting._update_enemy_inference(bot, controller)  # noqa: SLF001

    assert values_called["count"] == 0
    assert bot.symmetry_tile_cache_count == 2
    assert bot.best_symmetry_mode == "ROT180"


def test_timing_governor_uses_trusted_wave_1_8ms_budget():
    governor = timing.TimingGovernor.start_turn(1_000_000)
    assert governor.soft_deadline_ns == 2_900_000
    assert governor.hard_deadline_ns == 3_000_000
    assert governor.should_skip_low_priority(2_790_000) is True
    assert governor.is_hard_expired(3_000_001) is True


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


def test_economy_builder_builds_sentinel_against_visible_core_threat():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    # Connected conveyor adjacent to the sentinel build tile (12, 10) so
    # the per-tile supply gate reports the sentinel as feedable.
    bot.grid = {
        (12, 11): {
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        },
    }
    bot.connected_friendly_conveyors = {(12, 11): 1}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda pos, direction: pos == Position(12, 10)
        and direction == Direction.EAST,
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
        get_global_resources=lambda: (0, 0),
    )

    assert defense.defend_core_if_needed(bot, controller) is True
    assert built == [(Position(12, 10), Direction.EAST)]
    assert bot.last_defense_build_round == 30


def test_defense_skips_sentinel_when_economy_has_no_delivery_lane():
    """Port from user feedback: a defense bot must NOT panic-build a
    sentinel if no delivery lane exists and there is no titanium reserve,
    because the freshly-built gun will starve for ammo while the econ
    collapses. The emergency core-distance override does not apply at
    threat distance_sq = 9 > DEFENSE_EMERGENCY_CORE_DIST_SQ = 8."""
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    bot.grid = {}
    # No delivery lane, no titanium reserve.
    bot.connected_friendly_conveyors = {}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: True,
        build_sentinel=lambda *_args: built.append(_args),
        get_global_resources=lambda: (10, 0),
    )

    assert defense.defend_core_if_needed(bot, controller) is False
    assert built == []


def test_defense_builds_emergency_sentinel_for_threat_adjacent_to_core():
    """When the threat is within DEFENSE_EMERGENCY_CORE_DIST_SQ of the core
    AND a supply source exists adjacent to a viable build slot, build the
    sentinel even with no general delivery lane. A last-stand gun with
    ammo is better than losing the core outright, but a starving sentinel
    still wouldn't fire so the per-tile supply gate must still pass."""
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    # distance_sq from core = 4 (within 8 threshold).
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(12, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    # A friendly harvester adjacent to the sentinel build tile (12, 10) so
    # the per-tile supply gate reports the sentinel as feedable even with
    # no general connected conveyor lane.
    bot.grid = {
        (12, 11): {
            "building": EntityType.HARVESTER,
            "building_team": 1,
        },
    }
    bot.connected_friendly_conveyors = {}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: True,
        build_sentinel=lambda *_args: built.append(_args),
        get_global_resources=lambda: (0, 0),
    )

    assert defense.defend_core_if_needed(bot, controller) is True
    assert len(built) == 1


def test_defense_skips_emergency_sentinel_with_no_adjacent_supply():
    """Even in the emergency core-threat case, refuse to build a sentinel
    that will starve. A gun without ammo does not save the core — better to
    skip and let the turn be used for something else."""
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(12, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    # No adjacent supply anywhere → every candidate fails the supply gate.
    bot.grid = {}
    bot.connected_friendly_conveyors = {}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: True,
        build_sentinel=lambda *_args: built.append(_args),
        get_global_resources=lambda: (10_000, 0),  # plenty of Ti still blocked
    )

    assert defense.defend_core_if_needed(bot, controller) is False
    assert built == []


def test_core_defense_does_not_interrupt_tiling_back_lane():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    bot.grid = {}
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_core_defense_ignores_distant_enemy_builder_scout():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(17, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    bot.grid = {}
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_core_defense_skips_when_existing_visible_defense_is_present():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(11, 9), (9, 11)}
    bot.grid = {
        (11, 9): {"building": EntityType.SENTINEL, "building_team": 1},
        (9, 11): {"building": EntityType.SENTINEL, "building_team": 1},
    }
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_explorer_builds_near_core_lane_defense_for_visible_suppressed_harvester():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(17, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(18, 10)}
    bot.grid = {
        (18, 10): {
            "building": EntityType.HARVESTER,
            "building_team": 1,
            "building_hp": 60,
            "building_max_hp": 100,
        },
        # Connected conveyor adjacent to the sentinel build tile (16, 10)
        # so the per-tile supply gate recognises it as feedable.
        (16, 11): {
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.connected_friendly_conveyors = {(16, 11): 1}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda pos, direction: pos == Position(16, 10)
        and direction == Direction.EAST,
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
        get_global_resources=lambda: (0, 0),
    )

    assert defense.defend_lane_if_needed(bot, controller) is True
    assert built == [(Position(16, 10), Direction.EAST)]
    assert bot.last_defense_build_round == 30


def test_lane_defense_skips_far_from_core_to_avoid_overdefense():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(2, 2)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(17, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(18, 10)}
    bot.grid = {
        (18, 10): {"building": EntityType.HARVESTER, "building_team": 1},
    }
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_lane_defense_skips_loose_builder_contact_without_asset_damage():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(19, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(16, 10)}
    bot.grid = {
        (16, 10): {
            "building": EntityType.HARVESTER,
            "building_team": 1,
            "building_hp": 100,
            "building_max_hp": 100,
        },
    }
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_lane_defense_skips_adjacent_builder_without_asset_damage():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(17, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(18, 10)}
    bot.grid = {
        (18, 10): {
            "building": EntityType.HARVESTER,
            "building_team": 1,
            "building_hp": 100,
            "building_max_hp": 100,
        },
    }
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_lane_defense_allows_damaged_asset_against_nearby_builder():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(19, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(16, 10)}
    bot.grid = {
        (16, 10): {
            "building": EntityType.HARVESTER,
            "building_team": 1,
            "building_hp": 60,
            "building_max_hp": 100,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    # Economy-health gate: delivery lane exists → defense build allowed.
    bot.connected_friendly_conveyors = {(11, 10): 1}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda pos, direction: pos == Position(16, 9)
        and direction == Direction.EAST,
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
        get_global_resources=lambda: (0, 0),
    )

    assert defense.defend_lane_if_needed(bot, controller) is True
    assert built == [(Position(16, 9), Direction.EAST)]


def test_lane_defense_skips_when_existing_visible_lane_guard_is_present():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(17, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(18, 10), (18, 9)}
    bot.grid = {
        (18, 10): {"building": EntityType.HARVESTER, "building_team": 1},
        (18, 9): {"building": EntityType.SENTINEL, "building_team": 1},
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("can_build") or True,
        build_sentinel=lambda *_args: calls.append("build"),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert calls == []


def test_hijack_mode_tiles_back_when_target_is_lost_on_secured_entry(monkeypatch):
    bot = BuilderBot()
    bot.builder_mode = BuilderMode.HIJACKING
    bot.hijack_source_pos = Position(8, 8)
    bot.hijack_entry_pos = Position(8, 9)
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    calls = []

    monkeypatch.setattr(mode_hijacking, "find_visible_hijack_target", lambda *_args: None)
    monkeypatch.setattr(
        mode_finding_ore,
        "enter_tiling_back_from_origin",
        lambda _bot, start_pos, *, origin_kind: calls.append((start_pos, origin_kind)),
    )

    controller = SimpleNamespace(get_position=lambda: Position(8, 9))
    mode_hijacking.execute(bot, controller)

    assert calls == [(Position(8, 9), "HIJACK")]
    assert bot.builder_mode == BuilderMode.HIJACKING
    assert bot.hijack_source_pos is None
    assert bot.hijack_entry_pos is None


def test_builder_bot_opening_unclog_moves_econ_builder_off_spawn():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.spawn_pos = Position(0, 28)
    bot.core_pos = Position(1, 28)
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    moves = []
    controller = SimpleNamespace(
        get_current_round=lambda: 10,
        get_position=lambda: Position(0, 28),
        can_move=lambda direction: direction == Direction.SOUTH,
        move=lambda direction: moves.append(direction),
    )

    assert bot._maybe_opening_unclog(controller) is True
    assert moves == [Direction.SOUTH]


def test_tiling_back_uses_fast_perception_between_full_refreshes():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.last_full_perception_round = 50

    controller = SimpleNamespace(get_current_round=lambda: 55)
    assert bot._should_use_fast_perception(controller) is True

    controller = SimpleNamespace(get_current_round=lambda: 60)
    assert bot._should_use_fast_perception(controller) is False

    bot.last_full_perception_round = -1
    controller = SimpleNamespace(get_current_round=lambda: 55)
    assert bot._should_use_fast_perception(controller) is False

    bot.last_full_perception_round = 50
    bot.builder_mode = BuilderMode.FINDING_ORE
    assert bot._should_use_fast_perception(controller) is False


def test_economy_search_uses_fast_perception_between_full_refreshes():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.last_full_perception_round = 50

    controller = SimpleNamespace(get_current_round=lambda: 53)
    assert bot._should_use_fast_perception(controller) is True

    controller = SimpleNamespace(get_current_round=lambda: 54)
    assert bot._should_use_fast_perception(controller) is False

    bot.titanium_locations.add(Position(8, 8))
    controller = SimpleNamespace(get_current_round=lambda: 57)
    assert bot._should_use_fast_perception(controller) is True

    controller = SimpleNamespace(get_current_round=lambda: 58)
    assert bot._should_use_fast_perception(controller) is False


def test_fast_perception_inference_records_visible_ore():
    bot = BuilderBot()
    bot.is_assault_role = False
    ore_pos = Position(7, 9)
    bot.grid[(ore_pos.x, ore_pos.y)] = {
        "env": Environment.ORE_TITANIUM,
        "last_seen": 12,
        "entity": None,
        "building": None,
    }
    bot.visible_positions = {(ore_pos.x, ore_pos.y)}

    controller = SimpleNamespace(
        get_team=lambda *_args: "A",
        get_current_round=lambda: 12,
        get_position=lambda *_args: Position(5, 5),
        get_id=lambda: 3,
    )

    perception._infer_from_grid_fast(bot, controller, [], {})

    assert ore_pos in bot.titanium_locations
    assert (ore_pos.x, ore_pos.y) in bot.pathfinding_state["known_obstacles"]


def test_tiling_back_accepts_splitter_as_same_tile_merge_target():
    bot = SimpleNamespace(
        pending_build=None,
        connected_friendly_conveyors={(5, 3): 2},
        grid={
            (5, 3): {
                "building": EntityType.SPLITTER,
                "building_team": 1,
            }
        },
    )
    ct = SimpleNamespace(get_team=lambda: 1)

    assert mode_tiling_back._check_connect_to_conveyor(
        bot, ct, Position(5, 3), Position(5, 3), TargetKind.CONVEYOR
    )


def test_backpressured_adjacent_harvester_builds_secondary_core_return():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.grid = {
        (5, 4): {"building": None},
        (5, 6): {
            "building_id": 61,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
        },
    }
    bot.connected_friendly_conveyors = {(5, 6): 1}
    built = []
    controller = SimpleNamespace(
        get_current_round=lambda: 80,
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 4),
        build_harvester=lambda pos: built.append(pos),
        get_stored_resource_id=lambda entity_id: 900 if entity_id == 61 else None,
    )

    switched = mode_finding_ore._build_harvester_and_switch_mode(  # noqa: SLF001
        bot,
        controller,
        Position(5, 5),
    )

    assert switched is True
    assert built == [Position(5, 5)]
    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.tiling_force_core_return is True
    assert bot.return_target_kind == TargetKind.CORE
    assert (5, 5) not in bot.claimed_harvesters


def test_empty_adjacent_harvester_stays_claimed_without_secondary_route():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.grid = {
        (5, 4): {"building": None},
        (5, 6): {
            "building_id": 61,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
        },
    }
    bot.connected_friendly_conveyors = {(5, 6): 8}
    controller = SimpleNamespace(
        get_current_round=lambda: 80,
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 4),
        build_harvester=lambda _pos: None,
        get_stored_resource_id=lambda _entity_id: None,
        get_stored_resource=lambda _entity_id: None,
    )

    switched = mode_finding_ore._build_harvester_and_switch_mode(  # noqa: SLF001
        bot,
        controller,
        Position(5, 5),
    )

    assert switched is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.tiling_force_core_return is False
    assert (5, 5) in bot.claimed_harvesters


def test_forced_core_return_uses_stable_core_approach_slot():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.last_harvester_pos = Position(4, 10)
    bot.tiling_force_core_return = True
    controller = SimpleNamespace(
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
    )

    target = mode_tiling_back._select_core_return_target(  # noqa: SLF001
        bot,
        controller,
        Position(4, 10),
    )

    assert max(abs(target.x - 10), abs(target.y - 10)) <= 1
    assert bot.core_return_target_pos == target

    target_again = mode_tiling_back._select_core_return_target(  # noqa: SLF001
        bot,
        controller,
        Position(5, 10),
    )
    assert target_again == target


def test_blocked_assault_opening_escape_yields_to_economy():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(11, 11)
    bot.spawn_slot = 2
    bot.is_assault_role = True
    bot.builder_mode = BuilderMode.ASSAULTING
    bot.assault_opening_escape_complete = False
    bot.assault_bootstrap_state["blocked_turns"] = (
        mode_assaulting.ASSAULT_OPENING_ESCAPE_BLOCKED_LIMIT - 1
    )
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 11),
        get_current_round=lambda: 12,
        can_move=lambda _direction: False,
    )

    assert mode_assaulting.execute_opening_escape_only(bot, controller) is True
    assert bot.is_assault_role is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.assault_opening_escape_complete is True
    assert bot.pathfinding_state["path"] == []
    assert bot.assault_bootstrap_state["blocked_turns"] == 0


def test_ore_target_blacklists_after_repeated_stalls():
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    controller = SimpleNamespace(get_current_round=lambda: 50)
    ore_pos = Position(7, 9)
    access_pos = Position(6, 9)

    for _ in range(mode_finding_ore.ORE_TARGET_STUCK_RETRY_TURNS - 1):
        assert mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
            bot,
            controller,
            ore_pos,
            access_pos,
            moved=False,
        ) is False

    assert mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
        moved=False,
    ) is True
    assert (ore_pos.x, ore_pos.y) in bot.ore_target_blacklist


def test_ore_target_progress_resets_stall_counter_on_move():
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    controller = SimpleNamespace(get_current_round=lambda: 50)
    ore_pos = Position(7, 9)
    access_pos = Position(6, 9)

    mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
        moved=False,
    )
    assert bot.ore_target_state["stuck_turns"] == 1
    assert mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
        moved=True,
    ) is False
    assert bot.ore_target_state["stuck_turns"] == 0


def test_ore_target_blacklists_faster_while_stuck_near_spawn_shell():
    bot = BuilderBot()
    bot.spawn_pos = Position(0, 28)
    bot.last_harvester_pos = None
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_position=lambda: Position(1, 28),
    )
    ore_pos = Position(7, 9)
    access_pos = Position(6, 9)

    for _ in range(mode_finding_ore.EARLY_ORE_TARGET_STUCK_RETRY_TURNS - 1):
        assert mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
            bot,
            controller,
            ore_pos,
            access_pos,
            moved=False,
        ) is False

    assert mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
        moved=False,
    ) is True


def _make_blocker_move_fixture(*, other_id: int, my_id: int, blocker_tile):
    """Shared fixture helper for friendly-blocker yield-policy tests."""
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.last_harvester_pos = None
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.grid = {(12, 10): blocker_tile}
    bot.pathfinding_state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": None,
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": None,
    }
    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        can_build_road=lambda _pos: False,
        build_road=lambda _pos: None,
        can_move=lambda _direction: False,
        get_team=lambda: 1,
        get_current_round=lambda: 20,
        get_id=lambda: my_id,
    )
    return bot, controller


def test_try_pathfinding_move_waits_when_outranking_friendly_blocker(monkeypatch):
    """Port from jon-6: when the current bot outranks the friendly blocker on
    unit id AND the blocker is not attached to a harvester route, do not
    mark it as a temp obstacle — just wait for it to clear next turn."""
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *_args, **_kwargs: (
            (navigation.ActionType.CONVEYOR, Direction.EAST),
            {
                "known_obstacles": set(),
                "path": [(navigation.ActionType.CONVEYOR, Direction.EAST)],
                "temporary_obstacles": {},
                "current_target": (12, 10),
                "last_obstacle_signature": None,
                "last_replan_signature": None,
                "last_replan_round": -1,
                "planner_state": None,
            },
        ),
    )

    bot, controller = _make_blocker_move_fixture(
        other_id=99,
        my_id=5,
        blocker_tile={"entity": EntityType.BUILDER_BOT, "entity_team": 1, "id": 99},
    )

    moved, _ = navigation.try_pathfinding_move(bot, controller, Position(12, 10))

    assert moved is False
    # We outrank the blocker (5 < 99) so no obstacle is set — we just wait.
    assert (12, 10) not in bot.pathfinding_state["temporary_obstacles"]


def test_try_pathfinding_move_yields_to_lower_id_friendly_blocker(monkeypatch):
    """Port from jon-6: when the friendly blocker outranks us (lower id),
    mark it as a temp obstacle and route around. TTL is the shorter 3-turn
    window so stale obstacles clear quickly."""
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *_args, **_kwargs: (
            (navigation.ActionType.CONVEYOR, Direction.EAST),
            {
                "known_obstacles": set(),
                "path": [(navigation.ActionType.CONVEYOR, Direction.EAST)],
                "temporary_obstacles": {},
                "current_target": (12, 10),
                "last_obstacle_signature": None,
                "last_replan_signature": None,
                "last_replan_round": -1,
                "planner_state": None,
            },
        ),
    )

    bot, controller = _make_blocker_move_fixture(
        other_id=5,
        my_id=99,
        blocker_tile={"entity": EntityType.BUILDER_BOT, "entity_team": 1, "id": 5},
    )

    moved, _ = navigation.try_pathfinding_move(bot, controller, Position(12, 10))

    assert moved is False
    # We yield to the lower-id blocker so we reroute with a 3-turn TTL.
    assert bot.pathfinding_state["temporary_obstacles"][(12, 10)] == 23


def test_try_pathfinding_move_routes_around_blocker_attached_to_harvester(monkeypatch):
    """Port from jon-6: even when we outrank the friendly blocker on id,
    route around if they are attached to a harvester route (active tiling)."""
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *_args, **_kwargs: (
            (navigation.ActionType.CONVEYOR, Direction.EAST),
            {
                "known_obstacles": set(),
                "path": [(navigation.ActionType.CONVEYOR, Direction.EAST)],
                "temporary_obstacles": {},
                "current_target": (12, 10),
                "last_obstacle_signature": None,
                "last_replan_signature": None,
                "last_replan_round": -1,
                "planner_state": None,
            },
        ),
    )

    bot, controller = _make_blocker_move_fixture(
        other_id=99,
        my_id=5,
        blocker_tile={"entity": EntityType.BUILDER_BOT, "entity_team": 1, "id": 99},
    )
    # Blocker tile is adjacent to a friendly harvester, so the reverse trace
    # detects that it is attached to a route.
    bot.grid[(13, 10)] = {"building": EntityType.HARVESTER, "building_team": 1}

    moved, _ = navigation.try_pathfinding_move(bot, controller, Position(12, 10))

    assert moved is False
    assert bot.pathfinding_state["temporary_obstacles"][(12, 10)] == 23


def test_try_pathfinding_move_uses_opening_shell_escape_when_boxed_by_friends(monkeypatch):
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *_args, **_kwargs: (
            None,
            {
                "known_obstacles": set(),
                "path": [],
                "temporary_obstacles": {},
                "current_target": None,
                "last_obstacle_signature": None,
                "last_replan_signature": None,
                "last_replan_round": -1,
                "planner_state": None,
            },
        ),
    )

    moves = []
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.last_harvester_pos = None
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.grid = {
        (10, 9): {"entity": EntityType.BUILDER_BOT, "entity_team": 1},
        (10, 11): {"entity": EntityType.BUILDER_BOT, "entity_team": 1},
        (9, 10): {"entity": EntityType.BUILDER_BOT, "entity_team": 1},
    }
    bot.pathfinding_state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": None,
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": None,
    }
    controller = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        can_build_road=lambda _pos: False,
        build_road=lambda _pos: None,
        can_move=lambda direction: direction == Direction.EAST,
        move=lambda direction: moves.append(direction),
        get_team=lambda: 1,
        get_current_round=lambda: 20,
        get_id=lambda: 5,
        get_position_after_move=lambda: Position(11, 10),
    )

    moved, _ = navigation.try_pathfinding_move(bot, controller, Position(15, 10))

    assert moved is True
    assert moves == [Direction.EAST]


def test_assault_frontier_recovery_only_happens_once_within_window():
    bot = BuilderBot()
    bot.harvester_anchor = Position(12, 12)
    bot.harvester_anchor_last_seen_round = 50
    bot.assault_subrole = "approach"
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.assault_scout_state = {
        "target": (5, 5),
        "chunk": (1, 1),
        "anchor": (12, 12),
        "expires_round": 80,
    }
    controller = SimpleNamespace(
        get_current_round=lambda: 55,
    )

    recovered = mode_assaulting._maybe_recover_frontier_anchor(  # noqa: SLF001
        bot,
        controller,
        Position(12, 12),
        reason="navigation_blocked",
    )
    assert recovered is True
    assert bot.assault_subrole == "holder"
    assert bot.assault_committed_site is None
    assert bot.assault_scout_state["target"] is None

    recovered_again = mode_assaulting._maybe_recover_frontier_anchor(  # noqa: SLF001
        bot,
        controller,
        Position(12, 12),
        reason="navigation_blocked",
    )
    assert recovered_again is False


def test_greedy_fallback_uses_navigation_heuristic(monkeypatch):
    monkeypatch.setattr(
        navigation,
        "_heuristic",
        lambda nx, ny, tx, ty, cardinal_only, multiplier=1.0: 1
        if (nx, ny) == (0, 1)
        else 10,
    )

    action = navigation._get_greedy_fallback_action(  # noqa: SLF001
        SimpleNamespace(grid={}),
        SimpleNamespace(get_map_width=lambda: 10, get_map_height=lambda: 10),
        current_pos=Position(0, 0),
        target_pos=Position(5, 0),
        known_obstacles=set(),
        temporary_obstacles=set(),
        cardinal_only=True,
    )

    assert action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)


def test_astar_default_bridge_gating_skips_bridge_when_plan_is_pending():
    controller = SimpleNamespace(
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_team=lambda: 1,
        draw_indicator_dot=lambda *_args, **_kwargs: None,
    )
    start = Position(5, 5)
    target = Position(7, 7)
    surrounding_obstacles = {
        (4, 4),
        (4, 5),
        (4, 6),
        (5, 4),
        (5, 6),
        (6, 4),
        (6, 5),
        (6, 6),
    }

    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        pending_bridge_plan=None,
        grid={},
        connected_friendly_conveyors={},
        turn_decision_deadline_ns=0,
        logger=SimpleNamespace(print=lambda *_args, **_kwargs: None),
        stats={},
    )

    bridge_path = navigation.calculate_astar_path(
        bot,
        controller,
        start,
        target,
        known_obstacles=surrounding_obstacles,
        cardinal_only=False,
    )
    assert bridge_path == [(navigation.ActionType.BRIDGE, Position(7, 7))]

    bot.pending_bridge_plan = (start, target)
    no_bridge_path = navigation.calculate_astar_path(
        bot,
        controller,
        start,
        target,
        known_obstacles=surrounding_obstacles,
        cardinal_only=False,
    )
    assert no_bridge_path == []


def test_forced_core_return_prefers_core_over_visible_connected_lane():
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        connected_friendly_conveyors={(5, 10): 0},
        tiling_prefer_core_return=True,
    )

    mode_finding_ore._determine_return_target(bot, Position(5, 10))  # noqa: SLF001

    assert bot.return_target_kind == TargetKind.CORE
    assert bot.return_target_pos == Position(9, 10)


def test_far_harvester_can_still_join_existing_pipeline():
    bot = SimpleNamespace(
        core_pos=Position(25, 25),
        connected_friendly_conveyors={(5, 5): 0},
        tiling_prefer_core_return=False,
    )

    mode_finding_ore._determine_return_target(bot, Position(6, 5))  # noqa: SLF001

    assert bot.return_target_kind == TargetKind.CONVEYOR
    assert bot.return_target_pos == Position(5, 5)


def test_close_harvester_enters_direct_core_preference_with_pipeline_backup():
    bot = SimpleNamespace(
        tiling_back_origin_kind=None,
        last_harvester_pos=None,
        tiled_back_positions={(9, 9)},
        nearest_conveyor_pos=Position(1, 1),
        nearest_conveyor_dist_manhatten=3,
        return_target_pos=Position(3, 3),
        return_target_dist_manhatten=4,
        return_target_kind=TargetKind.CONVEYOR,
        core_return_target_pos=None,
        tiling_force_core_return=False,
        tiling_prefer_core_return=False,
        tiling_core_approach_full=False,
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
        connected_friendly_conveyors={(5, 10): 0},
        core_pos=Position(10, 10),
        builder_mode=BuilderMode.EXPLORING,
    )

    mode_finding_ore.enter_tiling_back_from_origin(
        bot,
        Position(5, 10),
        origin_kind="HARVESTER",
    )

    assert bot.tiling_prefer_core_return is True
    assert bot.tiling_force_core_return is False
    assert bot.return_target_kind == TargetKind.CORE
    assert bot.return_target_pos == Position(9, 10)


def test_visible_pressure_keeps_first_lane_direct_core_without_existing_pipeline():
    bot = SimpleNamespace(
        tiling_back_origin_kind=None,
        last_harvester_pos=None,
        tiled_back_positions=set(),
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_pos=None,
        return_target_dist_manhatten=float("inf"),
        return_target_kind=TargetKind.CORE,
        core_return_target_pos=None,
        tiling_force_core_return=False,
        tiling_prefer_core_return=False,
        tiling_core_approach_full=False,
        last_return_target_refresh_round=-1,
        pathfinding_state={
            "path": [],
            "temporary_obstacles": {},
            "last_replan_signature": None,
            "last_replan_round": -1,
        },
        explore_target_chunk=None,
        explore_target_pos=None,
        pending_bridge_plan=None,
        pending_build=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        connected_friendly_conveyors={},
        core_pos=Position(10, 10),
        builder_mode=BuilderMode.EXPLORING,
        visible_enemy_targets=[
            assault.VisibleEnemy(Position(6, 10), EntityType.BUILDER_BOT)
        ],
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )

    mode_finding_ore.enter_tiling_back_from_origin(
        bot,
        Position(5, 10),
        origin_kind="HARVESTER",
    )

    assert bot.tiling_prefer_core_return is True
    assert bot.return_target_kind == TargetKind.CORE
    assert bot.return_target_pos == Position(9, 10)


def test_direct_core_route_stall_falls_back_to_pipeline_merge():
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(5, 10),
        ore_target_blacklist={},
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        tiling_force_core_return=False,
        tiling_prefer_core_return=True,
        tiling_core_approach_full=False,
        core_return_target_pos=Position(9, 10),
        nearest_conveyor_pos=Position(5, 10),
        nearest_conveyor_dist_manhatten=0,
        return_target_pos=Position(9, 10),
        return_target_dist_manhatten=4,
        return_target_kind=TargetKind.CORE,
        pathfinding_state={
            "path": [(navigation.ActionType.CONVEYOR, Direction.EAST)],
            "planner_state": {"signature": "planner"},
            "last_replan_signature": ("x",),
            "tiling_back_nav_stall_turns": mode_tiling_back.DIRECT_CORE_FALLBACK_STALL_LIMIT - 1,
            "tiling_back_nav_stall_pos": (5, 10),
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    abandoned = mode_tiling_back._note_nav_stall(  # noqa: SLF001
        bot,
        controller,
        Position(5, 10),
        Position(5, 10),
    )

    assert abandoned is False
    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.tiling_prefer_core_return is False
    assert bot.return_target_pos is None
    assert bot.pathfinding_state["path"] == []


def test_direct_core_preference_falls_back_when_core_approaches_are_full():
    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_team=lambda: 1,
        is_in_vision=lambda _pos: True,
    )
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        connected_friendly_conveyors={(15, 10): 0},
        tiled_back_positions=set(),
        tiling_force_core_return=False,
        tiling_prefer_core_return=True,
        core_return_target_pos=None,
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_kind=TargetKind.CORE,
        last_return_target_refresh_round=-1,
        last_connected_refresh_round=0,
    )
    bot.grid = {}
    for slot in mode_tiling_back._core_approach_slots(bot, controller):  # noqa: SLF001
        bot.grid[(slot.x, slot.y)] = {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        }

    mode_tiling_back._update_return_target_while_tiling(  # noqa: SLF001
        bot,
        controller,
        Position(16, 10),
    )

    assert bot.return_target_kind == TargetKind.CONVEYOR
    assert bot.return_target_pos == Position(15, 10)


def test_direct_core_preference_keeps_core_when_any_approach_is_open():
    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_team=lambda: 1,
        is_in_vision=lambda _pos: True,
    )
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        connected_friendly_conveyors={(15, 10): 0},
        tiled_back_positions=set(),
        tiling_force_core_return=False,
        tiling_prefer_core_return=True,
        core_return_target_pos=None,
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_kind=TargetKind.CORE,
        last_return_target_refresh_round=-1,
        last_connected_refresh_round=0,
    )
    slots = mode_tiling_back._core_approach_slots(bot, controller)  # noqa: SLF001
    bot.grid = {}
    for slot in slots[1:]:
        bot.grid[(slot.x, slot.y)] = {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        }
    bot.grid[(slots[0].x, slots[0].y)] = {"env": Environment.EMPTY, "building": None}

    mode_tiling_back._update_return_target_while_tiling(  # noqa: SLF001
        bot,
        controller,
        Position(16, 10),
    )

    assert bot.return_target_kind == TargetKind.CORE


def test_near_core_direct_return_does_not_assume_bridge_capacity_multiplier():
    controller = SimpleNamespace(
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_team=lambda: 1,
        draw_indicator_dot=lambda *_args, **_kwargs: None,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        pending_bridge_plan=None,
        grid={},
        connected_friendly_conveyors={},
        turn_decision_deadline_ns=0,
        tiling_prefer_core_return=True,
        tiling_force_core_return=False,
        tiling_core_approach_full=True,
        logger=SimpleNamespace(print=lambda *_args, **_kwargs: None),
        stats={},
    )

    path = navigation.calculate_astar_path(
        bot,
        controller,
        Position(4, 5),
        Position(7, 5),
        known_obstacles=set(),
        cardinal_only=True,
    )

    assert path == [
        (navigation.ActionType.CONVEYOR, Direction.EAST),
        (navigation.ActionType.CONVEYOR, Direction.EAST),
        (navigation.ActionType.CONVEYOR, Direction.EAST),
    ]


def test_near_core_bridge_shortcut_is_disabled_without_direct_core_preference():
    controller = SimpleNamespace(
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_team=lambda: 1,
        draw_indicator_dot=lambda *_args, **_kwargs: None,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        pending_bridge_plan=None,
        grid={},
        connected_friendly_conveyors={},
        turn_decision_deadline_ns=0,
        tiling_prefer_core_return=False,
        tiling_force_core_return=False,
        tiling_core_approach_full=False,
        logger=SimpleNamespace(print=lambda *_args, **_kwargs: None),
        stats={},
    )

    path = navigation.calculate_astar_path(
        bot,
        controller,
        Position(4, 5),
        Position(7, 5),
        known_obstacles=set(),
        cardinal_only=True,
    )

    assert path == [
        (navigation.ActionType.CONVEYOR, Direction.EAST),
        (navigation.ActionType.CONVEYOR, Direction.EAST),
        (navigation.ActionType.CONVEYOR, Direction.EAST),
    ]


def test_assault_navigation_uses_local_escape_when_direct_step_is_blocked(monkeypatch):
    current_pos = Position(5, 5)
    moves = []
    controller = SimpleNamespace(
        get_position=lambda: current_pos,
        get_team=lambda: 1,
        get_current_round=lambda: 20,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_id=lambda: 99,
        can_build_road=lambda _pos: False,
        build_road=lambda _pos: None,
        can_move=lambda direction: direction == Direction.SOUTH,
        move=lambda direction: moves.append(direction),
        draw_indicator_line=lambda *_args, **_kwargs: None,
    )
    bot = SimpleNamespace(
        grid={(6, 5): {"entity": EntityType.BUILDER_BOT, "entity_team": 1, "id": 7}},
        pathfinding_state={"known_obstacles": set(), "temporary_obstacles": {}},
        assault_nav_state=None,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None, print=lambda *_args, **_kwargs: None),
        stats={},
    )
    monkeypatch.setattr(
        navigation,
        "_validate_assault_cached_bfs_path",
        lambda *_args, **_kwargs: [(navigation.ActionType.CONVEYOR, Direction.EAST)],
    )

    moved, reason = navigation.assault_navigate(
        bot,
        controller,
        Position(7, 5),
    )

    assert moved is True
    assert reason == "local_escape"
    assert moves == [Direction.SOUTH]


def test_anytime_astar_resumes_after_partial_slice(monkeypatch):
    monkeypatch.setattr(navigation, "ANYTIME_ASTAR_MIN_ITERATIONS", 1)
    monkeypatch.setattr(navigation, "ANYTIME_ASTAR_ITERATION_DIVISOR", 64)
    monkeypatch.setattr(navigation, "_get_astar_limits", lambda _bot: (48, 1_000_000))
    controller = SimpleNamespace(
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_team=lambda: 1,
        get_current_round=lambda: 5,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        pending_bridge_plan=None,
        grid={},
        connected_friendly_conveyors={},
        turn_decision_deadline_ns=0,
        logger=SimpleNamespace(print=lambda *_args, **_kwargs: None),
        stats={},
    )

    start = Position(0, 0)
    target = Position(12, 0)
    first_path, first_exact, planner = navigation._resume_anytime_astar(  # noqa: SLF001
        bot,
        controller,
        start,
        target,
        known_obstacles=set(),
        planner_state=None,
    )
    assert first_exact is False
    assert planner is not None
    assert first_path

    second_path, second_exact, resumed = navigation._resume_anytime_astar(  # noqa: SLF001
        bot,
        controller,
        start,
        target,
        known_obstacles=set(),
        planner_state=planner,
    )
    assert second_path
    assert len(second_path) >= len(first_path)
    if second_exact:
        assert resumed is None


def test_anytime_astar_partial_ranking_does_not_reconstruct_full_paths(monkeypatch):
    monkeypatch.setattr(navigation, "ANYTIME_ASTAR_MIN_ITERATIONS", 1)
    monkeypatch.setattr(navigation, "ANYTIME_ASTAR_ITERATION_DIVISOR", 64)
    monkeypatch.setattr(navigation, "_get_astar_limits", lambda _bot: (48, 1_000_000))

    reconstruct_calls = {"count": 0}
    original_reconstruct = navigation._reconstruct_parent_path  # noqa: SLF001

    def counting_reconstruct(*args, **kwargs):
        reconstruct_calls["count"] += 1
        return original_reconstruct(*args, **kwargs)

    monkeypatch.setattr(navigation, "_reconstruct_parent_path", counting_reconstruct)

    controller = SimpleNamespace(
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_team=lambda: 1,
        get_current_round=lambda: 5,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        pending_bridge_plan=None,
        grid={},
        connected_friendly_conveyors={},
        turn_decision_deadline_ns=0,
        logger=SimpleNamespace(print=lambda *_args, **_kwargs: None),
        stats={},
    )

    path, exact, planner = navigation._resume_anytime_astar(  # noqa: SLF001
        bot,
        controller,
        Position(0, 0),
        Position(12, 0),
        known_obstacles=set(),
        planner_state=None,
    )

    assert exact is False
    assert planner is not None
    assert path
    assert reconstruct_calls["count"] == 1


def test_repeated_replan_uses_anytime_partial_instead_of_greedy(monkeypatch):
    monkeypatch.setattr(
        navigation,
        "calculate_micro_plan",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        navigation,
        "get_available_astar_time_budget",
        lambda *_args, **_kwargs: 1_000_000,
    )
    monkeypatch.setattr(
        navigation,
        "_resume_anytime_astar",
        lambda *_args, **_kwargs: (
            [(navigation.ActionType.CONVEYOR, Direction.SOUTH)],
            False,
            {"signature": "planner"},
        ),
    )

    move_action, new_state = navigation.compute_pathfinding_step(
        SimpleNamespace(
            builder_mode=BuilderMode.FINDING_ORE,
            grid={},
            connected_friendly_conveyors={},
            pending_bridge_plan=None,
            stats={},
        ),
        SimpleNamespace(
            get_current_round=lambda: 10,
            get_team=lambda: 1,
            get_map_width=lambda: 20,
            get_map_height=lambda: 20,
            get_position=lambda: Position(0, 0),
        ),
        Position(0, 0),
        Position(5, 0),
        {
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "current_target": (5, 0),
            "last_obstacle_signature": None,
            "last_replan_signature": (0, 0, (5, 0)),
            "last_replan_round": 10,
            "planner_state": None,
        },
    )

    assert move_action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)
    assert new_state["path"] == [(navigation.ActionType.CONVEYOR, Direction.SOUTH)]


def test_planner_signature_changes_when_obstacle_identity_changes():
    start = Position(0, 0)
    target = Position(5, 0)

    first = navigation._planner_signature(  # noqa: SLF001
        start,
        target,
        {(1, 0), (2, 0)},
        {(3, 0)},
        cardinal_only=False,
        tiling_back=False,
        allow_bridges=False,
    )
    second = navigation._planner_signature(  # noqa: SLF001
        start,
        target,
        {(1, 1), (2, 1)},
        {(3, 1)},
        cardinal_only=False,
        tiling_back=False,
        allow_bridges=False,
    )

    assert first != second


def test_compute_pathfinding_step_keeps_persistent_planner_object():
    planner = {
        "signature": ("same",),
        "open_set": [],
        "came_from": {},
        "g_costs": {},
        "depths": {},
    }
    move_action, new_state = navigation.compute_pathfinding_step(
        SimpleNamespace(
            builder_mode=BuilderMode.FINDING_ORE,
            grid={},
            connected_friendly_conveyors={},
            pending_bridge_plan=None,
            stats={},
        ),
        SimpleNamespace(
            get_current_round=lambda: 10,
            get_team=lambda: 1,
            get_map_width=lambda: 20,
            get_map_height=lambda: 20,
        ),
        Position(0, 0),
        Position(0, 1),
        {
            "known_obstacles": set(),
            "path": [(navigation.ActionType.CONVEYOR, Direction.SOUTH)],
            "temporary_obstacles": {},
            "current_target": (0, 1),
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
            "planner_state": planner,
        },
    )

    assert move_action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)
    assert new_state["planner_state"] is planner


def test_shared_progress_recovery_clears_tiling_back_pending_build_on_ping_pong():
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        pathfinding_state={
            "path": [(navigation.ActionType.CONVEYOR, Direction.NORTH)],
            "planner_state": {"signature": "planner"},
            "temporary_obstacles": {},
            "last_replan_signature": ("x",),
            "last_replan_round": 5,
        },
        pending_build=("build",),
        pending_bridge_plan=("bridge",),
        bridge_transit_path=[(navigation.ActionType.CONVEYOR, Direction.EAST)],
        bridge_transit_cooldown_until=99,
        saved_post_bridge_path=[(navigation.ActionType.CONVEYOR, Direction.WEST)],
    )
    controller = SimpleNamespace(get_current_round=lambda: 20)
    target = Position(10, 10)

    positions = [
        Position(4, 4),
        Position(4, 5),
        Position(4, 4),
        Position(4, 5),
        Position(4, 4),
        Position(4, 5),
    ]
    for pos in positions:
        navigation.note_shared_builder_progress(
            bot,
            controller,
            target,
            start_pos=pos,
            final_pos=pos,
            moved=True,
        )

    assert bot.pending_build is None
    assert bot.pending_bridge_plan is None
    assert bot.bridge_transit_path is None
    assert bot.bridge_transit_cooldown_until == -1
    assert bot.saved_post_bridge_path == []
    assert bot.pathfinding_state["path"] == []
    assert bot.pathfinding_state["planner_state"] is None
    assert bot.pathfinding_state["temporary_obstacles"] == {(4, 4): 32}


def test_shared_progress_stall_flag_is_consumed_once():
    bot = SimpleNamespace(pathfinding_state={"shared_progress_stalled": True})

    assert navigation.consume_shared_progress_stall(bot) is True
    assert navigation.consume_shared_progress_stall(bot) is False


def test_pending_build_stall_abandons_after_threshold():
    """A pending conveyor build that fails for PENDING_BUILD_STALL_LIMIT turns
    should be abandoned and the blocked position added as a temp obstacle."""
    from states import ActionType

    build_pos = Position(5, 5)
    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, build_pos, Direction.NORTH),
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "path": [(navigation.ActionType.CONVEYOR, Direction.NORTH)],
            "planner_state": {"signature": "planner"},
            "temporary_obstacles": {},
            "last_replan_signature": ("x",),
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    # First STALL_LIMIT - 1 calls should return False (not yet abandoned)
    for i in range(mode_tiling_back.PENDING_BUILD_STALL_LIMIT - 1):
        result = mode_tiling_back._note_pending_build_stall(bot, controller, succeeded=False)
        assert result is False, f"Should not abandon on turn {i + 1}"
        assert bot.pending_build is not None

    # The next call should trigger abandonment
    result = mode_tiling_back._note_pending_build_stall(bot, controller, succeeded=False)
    assert result is True
    assert bot.pending_build is None
    assert bot.pathfinding_state["path"] == []
    assert bot.pathfinding_state["planner_state"] is None
    assert (5, 5) in bot.pathfinding_state["temporary_obstacles"]
    assert bot.pathfinding_state["temporary_obstacles"][(5, 5)] == 100 + mode_tiling_back.PENDING_BUILD_TEMP_OBSTACLE_TTL


def test_pending_build_stall_resets_on_success():
    """A successful build should reset the stall counter."""
    from states import ActionType

    build_pos = Position(5, 5)
    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, build_pos, Direction.NORTH),
        pathfinding_state={"temporary_obstacles": {}},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    # Accumulate some stall turns
    for _ in range(mode_tiling_back.PENDING_BUILD_STALL_LIMIT - 2):
        mode_tiling_back._note_pending_build_stall(bot, controller, succeeded=False)

    assert bot.pathfinding_state.get("pending_build_stall_turns", 0) > 0

    # Succeed — counter should reset
    mode_tiling_back._note_pending_build_stall(bot, controller, succeeded=True)
    assert bot.pathfinding_state.get("pending_build_stall_turns") is None
    assert bot.pathfinding_state.get("pending_build_stall_pos") is None


def test_pending_build_stall_resets_on_position_change():
    """If the pending build moves to a new position, the stall counter should reset."""
    from states import ActionType

    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, Position(5, 5), Direction.NORTH),
        pathfinding_state={"temporary_obstacles": {}},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    # Accumulate some stall turns at (5, 5)
    for _ in range(mode_tiling_back.PENDING_BUILD_STALL_LIMIT - 2):
        mode_tiling_back._note_pending_build_stall(bot, controller, succeeded=False)

    turns_before = bot.pathfinding_state["pending_build_stall_turns"]
    assert turns_before > 0

    # Change pending build to a different position
    bot.pending_build = (ActionType.CONVEYOR, Position(7, 7), Direction.SOUTH)
    mode_tiling_back._note_pending_build_stall(bot, controller, succeeded=False)
    assert bot.pathfinding_state["pending_build_stall_turns"] == 1
    assert bot.pathfinding_state["pending_build_stall_pos"] == (7, 7)


def test_execute_pending_build_returns_false_on_stall_abandonment():
    """When a pending build is abandoned due to stall, _execute_pending_build
    should return False so that _navigate_and_build runs this turn."""
    from states import ActionType

    build_pos = Position(5, 5)
    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, build_pos, Direction.NORTH),
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        tiled_back_positions=set(),
        grid={(5, 5): {"building": EntityType.BARRIER, "building_team": 2, "building_dir": None}},
        pathfinding_state={
            "path": [(navigation.ActionType.CONVEYOR, Direction.NORTH)],
            "planner_state": {"signature": "planner"},
            "temporary_obstacles": {},
            "last_replan_signature": ("x",),
            "pending_build_stall_turns": mode_tiling_back.PENDING_BUILD_STALL_LIMIT - 1,
            "pending_build_stall_pos": (5, 5),
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    fire_calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 100,
        get_team=lambda: 1,
        can_build_conveyor=lambda *_args: False,
        can_fire=lambda _pos: True,
        fire=lambda _pos: fire_calls.append(_pos),
    )

    result = mode_tiling_back._execute_pending_build(bot, controller)

    # Should return False — navigation can proceed
    assert result is False
    assert bot.pending_build is None
    assert (5, 5) in bot.pathfinding_state["temporary_obstacles"]


def test_clear_obstacles_destroys_road_when_called_because_build_blocked():
    """When the caller determined that can_build_conveyor is False and asked
    to clear the tile, the road is destroyed so the next conveyor build
    can succeed. The hygiene improvement is at the CALLER level —
    lookahead now only calls _clear_obstacles_for_conveyor when the build
    actually cannot proceed, instead of unconditionally."""
    pos = Position(5, 5)
    bot = SimpleNamespace(
        grid={
            (5, 5): {
                "building": EntityType.ROAD,
                "building_team": 1,
            }
        },
        connected_friendly_conveyors={},
        claimed_pipeline_positions=set(),
        tiled_back_positions=set(),
        known_friendly_conveyors=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda *_args: calls.append("destroy?") or True,
        destroy=lambda *_args: calls.append("destroy"),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(  # noqa: SLF001
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert "destroy" in calls
    # Path state is untouched — no protect-temp-obstacle path fires for roads.
    assert bot.pathfinding_state["path"] == ["stale"]


def test_clear_obstacles_still_destroys_marker_before_conveyor():
    """Counterpart to the road test: markers still need a pre-build destroy
    because they block construction on the tile."""
    pos = Position(5, 5)
    bot = SimpleNamespace(
        grid={
            (5, 5): {
                "building": EntityType.MARKER,
                "building_team": 1,
            }
        },
        connected_friendly_conveyors={},
        claimed_pipeline_positions=set(),
        tiled_back_positions=set(),
        known_friendly_conveyors=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda *_args: calls.append("destroy?") or True,
        destroy=lambda *_args: calls.append("destroy") or None,
    )

    mode_tiling_back._clear_obstacles_for_conveyor(  # noqa: SLF001
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert "destroy" in calls, "markers still need to be destroyed before a build"


def test_clear_obstacles_preserves_friendly_pipeline():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            }
        },
        connected_friendly_conveyors={(5, 5): 1},
        claimed_pipeline_positions=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: calls.append("fire?") or False,
        can_destroy=lambda *_args: calls.append("destroy?") or True,
        destroy=lambda *_args: calls.append("destroy"),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert calls == []
    assert bot.pathfinding_state["temporary_obstacles"][(5, 5)] == (
        50 + mode_tiling_back.PENDING_BUILD_TEMP_OBSTACLE_TTL
    )
    assert bot.pathfinding_state["path"] == []


def test_clear_obstacles_preserves_claimed_partial_pipeline():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            }
        },
        connected_friendly_conveyors={},
        claimed_pipeline_positions={(5, 5)},
        tiled_back_positions=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda *_args: calls.append("destroy?") or True,
        destroy=lambda *_args: calls.append("destroy"),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert calls == []
    assert bot.pathfinding_state["temporary_obstacles"][(5, 5)] == (
        50 + mode_tiling_back.PENDING_BUILD_TEMP_OBSTACLE_TTL
    )
    assert bot.pathfinding_state["path"] == []


def test_clear_obstacles_preserves_unconnected_friendly_conveyor():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            }
        },
        connected_friendly_conveyors={},
        claimed_pipeline_positions=set(),
        tiled_back_positions=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda pos: calls.append(("can_destroy", pos)) or True,
        destroy=lambda pos: calls.append(pos),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert calls == []
    assert bot.pathfinding_state["temporary_obstacles"][(5, 5)] == (
        50 + mode_tiling_back.PENDING_BUILD_TEMP_OBSTACLE_TTL
    )
    assert bot.pathfinding_state["path"] == []


def test_clear_obstacles_allows_owned_unconnected_conveyor_repair():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            }
        },
        connected_friendly_conveyors={},
        claimed_pipeline_positions=set(),
        tiled_back_positions={(5, 5)},
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda pos: pos == Position(5, 5),
        destroy=lambda pos: calls.append(pos),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert calls == [Position(5, 5)]
    assert bot.pathfinding_state["path"] == ["stale"]


def test_pending_conveyor_build_preserves_conflicting_friendly_pipeline():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, pos, Direction.NORTH),
        tiled_back_positions=set(),
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            }
        },
        connected_friendly_conveyors={(5, 5): 1},
        claimed_pipeline_positions=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_build_conveyor=lambda *_args: calls.append("can_build") or True,
        build_conveyor=lambda *_args: calls.append("build"),
    )

    assert mode_tiling_back._execute_pending_build(bot, controller) is False
    assert calls == []
    assert bot.pending_build is None
    assert bot.tiled_back_positions == set()
    assert (5, 5) in bot.pathfinding_state["temporary_obstacles"]


def test_pending_conveyor_build_preserves_unconnected_friendly_pipeline():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, pos, Direction.NORTH),
        tiled_back_positions=set(),
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            }
        },
        connected_friendly_conveyors={},
        claimed_pipeline_positions=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_build_conveyor=lambda *_args: calls.append("can_build") or True,
        build_conveyor=lambda *_args: calls.append("build"),
    )

    assert mode_tiling_back._execute_pending_build(bot, controller) is False
    assert calls == []
    assert bot.pending_build is None
    assert bot.tiled_back_positions == set()
    assert (5, 5) in bot.pathfinding_state["temporary_obstacles"]


def test_pending_conveyor_build_accepts_matching_friendly_pipeline():
    pos = Position(5, 5)
    bot = SimpleNamespace(
        pending_build=(ActionType.CONVEYOR, pos, Direction.NORTH),
        tiled_back_positions=set(),
        grid={
            (5, 5): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.NORTH,
            }
        },
        connected_friendly_conveyors={(5, 5): 1},
        claimed_pipeline_positions=set(),
        shared_pipeline_claim_positions=set(),
        last_pipeline_claim_round=-9999,
        core_pos=Position(10, 10),
        titanium_locations=set(),
        axionite_locations=set(),
        known_friendly_conveyors=set(),
        pathfinding_state={},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_build_conveyor=lambda *_args: calls.append("can_build") or True,
        build_conveyor=lambda *_args: calls.append("build"),
    )

    assert mode_tiling_back._execute_pending_build(bot, controller) is False
    assert calls == []
    assert bot.pending_build is None
    assert bot.tiled_back_positions == {(5, 5)}


def test_core_lane_slot_assignment_is_stable_when_enabled():
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        core_return_target_pos=None,
        core_lane_slot_pos=None,
        core_lane_core_tile_pos=None,
        tiling_force_core_return=False,
        tiling_prefer_core_return=True,
        spawn_pos=Position(10, 12),
        last_harvester_pos=Position(15, 14),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_id=lambda: 7,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
    )

    slot = mode_tiling_back._assign_core_lane_slot(
        bot,
        controller,
        Position(15, 14),
    )

    assert mode_tiling_back._is_core_approach_slot(bot, slot)
    assert slot == bot.core_lane_slot_pos
    assert abs(bot.core_lane_core_tile_pos.x - bot.core_pos.x) <= 1
    assert abs(bot.core_lane_core_tile_pos.y - bot.core_pos.y) <= 1


def test_core_slot_exit_builds_final_conveyor_before_completion():
    slot = Position(10, 8)
    core_tile = Position(10, 9)
    builds = []
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        core_lane_slot_pos=slot,
        core_lane_core_tile_pos=core_tile,
        core_lane_exit_built=False,
        pending_build=None,
        tiled_back_positions=set(),
        claimed_pipeline_positions=set(),
        shared_pipeline_claim_positions=set(),
        last_pipeline_claim_round=-9999,
        connected_friendly_conveyors={},
        known_friendly_conveyors=set(),
        titanium_locations=set(),
        axionite_locations=set(),
        grid={(10, 8): {"env": None}},
        pathfinding_state={"temporary_obstacles": {}, "path": []},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        get_position=lambda: slot,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_conveyor=lambda pos, direction: pos == slot
        and direction == utils.direction_toward(slot, core_tile),
        build_conveyor=lambda pos, direction: builds.append((pos, direction)),
        can_place_marker=lambda *_args: False,
        can_fire=lambda *_args: False,
        can_destroy=lambda *_args: False,
    )

    consumed = mode_tiling_back._ensure_core_slot_exit(
        bot,
        controller,
        slot,
        slot,
        TargetKind.CORE,
    )

    assert consumed is False
    assert builds == [(slot, utils.direction_toward(slot, core_tile))]
    assert bot.core_lane_exit_built is True
    assert mode_tiling_back._is_at_core(
        bot,
        controller,
        slot,
        slot,
        TargetKind.CORE,
    )


def test_pipeline_claim_marker_uses_safe_side_tile():
    placements = []
    claimed_pos = Position(5, 5)
    safe_marker_pos = Position(6, 5)
    bot = SimpleNamespace(
        core_pos=Position(15, 15),
        shared_pipeline_claim_positions=set(),
        claimed_pipeline_positions=set(),
        connected_friendly_conveyors={},
        known_friendly_conveyors=set(),
        titanium_locations=set(),
        axionite_locations=set(),
        grid={
            (6, 5): {"env": None},
            (5, 4): {"env": None},
        },
        last_pipeline_claim_round=-9999,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_position=lambda: claimed_pos,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_place_marker=lambda pos: pos == safe_marker_pos,
        place_marker=lambda pos, value: placements.append((pos, value)),
    )

    assert mode_tiling_back._try_share_pipeline_claim_marker(
        bot,
        controller,
        claimed_pos,
        Direction.NORTH,
        reserved_keys={(5, 5), (5, 4)},
    )

    assert placements[0][0] == safe_marker_pos
    parsed = marker.parse_pipeline_claim_marker(placements[0][1], 30, 30)
    assert parsed == (claimed_pos, 50)
    assert bot.shared_pipeline_claim_positions == {(5, 5)}


def test_tiling_back_nav_stall_abandons_after_threshold():
    """A builder stuck in TILING_BACK for NAV_STALL_LIMIT turns without
    moving should abandon and switch to FINDING_ORE."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(10, 10),
        ore_target_blacklist={},
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "path": [],
            "planner_state": None,
            "last_replan_signature": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)
    stuck_pos = Position(5, 5)

    # First NAV_STALL_LIMIT - 1 calls: no abandonment
    for i in range(mode_tiling_back.NAV_STALL_LIMIT - 1):
        result = mode_tiling_back._note_nav_stall(bot, controller, stuck_pos, stuck_pos)
        assert result is False, f"Should not abandon on turn {i + 1}"
        assert bot.builder_mode == BuilderMode.TILING_BACK

    # NAV_STALL_LIMIT-th call triggers abandonment
    result = mode_tiling_back._note_nav_stall(bot, controller, stuck_pos, stuck_pos)
    assert result is True
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    # Harvester should be blacklisted
    assert (10, 10) in bot.ore_target_blacklist
    assert bot.ore_target_blacklist[(10, 10)] == 100 + mode_tiling_back.NAV_STALL_BLACKLIST_BASE_TTL


def test_tiling_back_nav_stall_resets_on_movement():
    """Movement resets the nav stall counter."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(10, 10),
        ore_target_blacklist={},
        pathfinding_state={},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    # Accumulate some stall turns
    for _ in range(mode_tiling_back.NAV_STALL_LIMIT - 2):
        mode_tiling_back._note_nav_stall(bot, controller, Position(5, 5), Position(5, 5))

    assert bot.pathfinding_state.get("tiling_back_nav_stall_turns", 0) > 0

    # Move resets the counter
    mode_tiling_back._note_nav_stall(bot, controller, Position(5, 5), Position(5, 6))
    assert bot.pathfinding_state.get("tiling_back_nav_stall_turns") is None


def test_tiling_back_nav_stall_does_not_blacklist_hijack_origin():
    """When abandoning a HIJACK-origin tiling-back, don't blacklist the
    harvester since it wasn't ours."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HIJACK",
        last_harvester_pos=Position(10, 10),
        ore_target_blacklist={},
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "path": [],
            "planner_state": None,
            "last_replan_signature": None,
            "tiling_back_nav_stall_turns": mode_tiling_back.NAV_STALL_LIMIT - 1,
            "tiling_back_nav_stall_pos": (5, 5),
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    result = mode_tiling_back._note_nav_stall(bot, controller, Position(5, 5), Position(5, 5))
    assert result is True
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    # Should NOT blacklist since origin is HIJACK, not HARVESTER
    assert (10, 10) not in bot.ore_target_blacklist


def test_tiling_back_ping_pong_detected_and_abandoned():
    """Builders oscillating between 2 positions in TILING_BACK should be
    abandoned after enough oscillation windows."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(10, 10),
        ore_target_blacklist={},
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "path": [],
            "planner_state": None,
            "last_replan_signature": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(get_current_round=lambda: 100)

    pos_a = Position(5, 5)
    pos_b = Position(5, 6)
    trigger_count = mode_tiling_back.NAV_STALL_LIMIT // mode_tiling_back.NAV_PING_PONG_HISTORY
    total_turns_needed = trigger_count * mode_tiling_back.NAV_PING_PONG_HISTORY

    result = False
    for i in range(total_turns_needed + mode_tiling_back.NAV_PING_PONG_HISTORY):
        if i % 2 == 0:
            result = mode_tiling_back._note_nav_stall(bot, controller, pos_b, pos_a)
        else:
            result = mode_tiling_back._note_nav_stall(bot, controller, pos_a, pos_b)
        if result:
            break

    assert result is True, f"Ping-pong should have been detected within {total_turns_needed} turns"
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_tiling_back_escalating_blacklist():
    """Repeated tiling-back failures on the same harvester should escalate
    the blacklist TTL and eventually become permanent."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(10, 10),
        ore_target_blacklist={},
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "path": [],
            "planner_state": None,
            "last_replan_signature": None,
            "tiling_back_nav_stall_turns": mode_tiling_back.NAV_STALL_LIMIT - 1,
            "tiling_back_nav_stall_pos": (5, 5),
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )

    # First failure
    controller = SimpleNamespace(get_current_round=lambda: 100)
    mode_tiling_back._note_nav_stall(bot, controller, Position(5, 5), Position(5, 5))
    first_ttl = bot.ore_target_blacklist[(10, 10)] - 100
    assert first_ttl == mode_tiling_back.NAV_STALL_BLACKLIST_BASE_TTL

    # Second failure (reset bot state)
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.pathfinding_state["tiling_back_nav_stall_turns"] = mode_tiling_back.NAV_STALL_LIMIT - 1
    bot.pathfinding_state["tiling_back_nav_stall_pos"] = (5, 5)
    controller2 = SimpleNamespace(get_current_round=lambda: 300)
    mode_tiling_back._note_nav_stall(bot, controller2, Position(5, 5), Position(5, 5))
    second_ttl = bot.ore_target_blacklist[(10, 10)] - 300
    assert second_ttl > first_ttl

    # Third failure → permanent
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.pathfinding_state["tiling_back_nav_stall_turns"] = mode_tiling_back.NAV_STALL_LIMIT - 1
    bot.pathfinding_state["tiling_back_nav_stall_pos"] = (5, 5)
    controller3 = SimpleNamespace(get_current_round=lambda: 600)
    mode_tiling_back._note_nav_stall(bot, controller3, Position(5, 5), Position(5, 5))
    third_ttl = bot.ore_target_blacklist[(10, 10)] - 600
    assert third_ttl >= 500


def test_assault_economy_fallback_transitions_after_stall():
    """An assault builder with no progress for ASSAULT_ECONOMY_FALLBACK_TURNS
    should transition to FINDING_ORE."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.ASSAULTING,
        is_assault_role=True,
        assault_last_progress_round=10,
        harvester_anchor=Position(15, 15),
        harvester_anchor_last_seen_round=10,
        assault_anchor_status="LIVE",
        assault_last_site_signature=None,
        assault_subrole="scout",
        assault_frontier_reset_state={
            "anchor": None,
            "last_round": -9999,
            "count": 0,
        },
        assault_committed_site=None,
        assault_committed_site_round=-9999,
        assault_execute_state={
            "subplan": None,
            "anchor": None,
            "ring": None,
            "direction": None,
            "wait_turns": 0,
            "fire_wait_turns": 0,
            "clear_attempts": 0,
        },
        assault_nav_failure_count=0,
        assault_progress_stall_count=0,
        assault_best_dist_to_ring=9999,
        assault_nav_progress_target=None,
        assault_scout_state={
            "target": None,
            "chunk": None,
            "anchor": None,
            "expires_round": -1,
        },
        assault_bootstrap_state={
            "target": None,
            "path": [],
            "expires_round": -1,
            "blocked_turns": 0,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 10 + mode_assaulting.ASSAULT_ECONOMY_FALLBACK_TURNS + 1,
    )

    mode_assaulting._maybe_transition_to_economy(bot, controller)

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.is_assault_role is False


def test_assault_economy_fallback_does_not_fire_early():
    """Before the stall limit, the assault builder should remain in ASSAULTING."""
    bot = SimpleNamespace(
        builder_mode=BuilderMode.ASSAULTING,
        is_assault_role=True,
        assault_last_progress_round=50,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 50 + mode_assaulting.ASSAULT_ECONOMY_FALLBACK_TURNS - 1,
    )

    mode_assaulting._maybe_transition_to_economy(bot, controller)

    assert bot.builder_mode == BuilderMode.ASSAULTING
    assert bot.is_assault_role is True


def test_core_bonus_assault_requires_economy_health():
    """The core should not spawn bonus assault builders until the economy
    has had time to establish (round >= 80)."""
    from core_bot import CoreBot

    core = CoreBot()
    # Early game: quota stays at opening wave size regardless of titanium.
    controller_early = SimpleNamespace(
        get_global_resources=lambda: (200, 0),
        get_current_round=lambda: 50,
    )
    assert core._assault_quota(controller_early) == 2

    # After economy established AND titanium threshold: quota increases.
    controller_late = SimpleNamespace(
        get_global_resources=lambda: (200, 0),
        get_current_round=lambda: 100,
    )
    assert core._assault_quota(controller_late) == 3

    # After economy established but insufficient titanium: stays at opening size.
    controller_late_low = SimpleNamespace(
        get_global_resources=lambda: (50, 0),
        get_current_round=lambda: 100,
    )
    assert core._assault_quota(controller_late_low) == 2
