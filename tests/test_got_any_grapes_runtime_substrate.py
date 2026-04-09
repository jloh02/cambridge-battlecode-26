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
import mode_assaulting  # noqa: E402
import assault  # noqa: E402
import mode_hijacking  # noqa: E402
import mode_tiling_back  # noqa: E402
import navigation  # noqa: E402
from builder_bot import BuilderBot  # noqa: E402
from states import BuilderMode, TargetKind  # noqa: E402
import timing  # noqa: E402


def teardown_module() -> None:
    for module_name in (
        "marker",
        "perception",
        "mode_finding_ore",
        "mode_assaulting",
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
        SimpleNamespace(),
        _SnapshotController(),
        [Position(0, 0), Position(1, 0)],
        include_building_health=True,
    )

    assert nearby_buildings == [1, 2]
    assert hp_reads == [("hp", 1), ("max_hp", 1)]
    assert nearby_cache[1]["hp"] == 100
    assert "hp" not in nearby_cache[2]


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


def test_try_pathfinding_move_marks_friendly_blocker_in_opening_shell(monkeypatch):
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

    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.last_harvester_pos = None
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.grid = {(12, 10): {"entity": EntityType.BUILDER_BOT, "entity_team": 1, "id": 99}}
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
        get_id=lambda: 5,
    )

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
    assert bot.pathfinding_state["temporary_obstacles"] == {(4, 4): 26}


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


def test_core_bonus_assault_requires_connected_economy():
    """The core should not spawn bonus assault builders until a connected
    economy (conveyor marker) has been observed."""
    from core_bot import CoreBot

    core = CoreBot()
    controller = SimpleNamespace(
        get_global_resources=lambda: (200, 0),
    )

    # Without connected economy, quota should equal opening wave size
    assert core._assault_quota(controller) == 2

    # With connected economy AND titanium threshold, quota should increase
    core.has_connected_economy = True
    assert core._assault_quota(controller) == 3

    # With connected economy but insufficient titanium, quota stays at opening size
    controller_low_ti = SimpleNamespace(
        get_global_resources=lambda: (50, 0),
    )
    assert core._assault_quota(controller_low_ti) == 2
