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
import mode_rush  # noqa: E402
import assault  # noqa: E402
import mode_hijacking  # noqa: E402
import mode_tiling_back  # noqa: E402
import mode_exploring  # noqa: E402
import navigation  # noqa: E402
import defense  # noqa: E402
import utils  # noqa: E402
import builder_bot  # noqa: E402
import main as got_any_grapes_main  # noqa: E402
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
        "mode_rush",
        "mode_hijacking",
        "mode_tiling_back",
        "mode_exploring",
        "defense",
        "builder_bot",
        "main",
        "sentinel_bot",
        "states",
        "timing",
        "utils",
    ):
        sys.modules.pop(module_name, None)
    while str(BOT_ROOT) in sys.path:
        sys.path.remove(str(BOT_ROOT))


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


def test_assault_threat_scoring_filters_non_threatening_logistics():
    harvester_pos = Position(10, 10)
    enemies = [assault.VisibleEnemy(harvester_pos, EntityType.HARVESTER)]
    enemies.extend(
        assault.VisibleEnemy(Position(30 + index, 30), EntityType.CONVEYOR)
        for index in range(20)
    )
    grid = {
        (10, 10): {
            "env": Environment.ORE_TITANIUM,
            "building": EntityType.HARVESTER,
            "building_team": 2,
        }
    }
    for direction in assault.CARDINAL_DIRECTIONS:
        ring = harvester_pos.add(direction)
        grid[(ring.x, ring.y)] = {"env": Environment.EMPTY, "building": None}
    profile = {}

    sites = assault.rank_assault_sites_for_harvester(
        harvester_position=harvester_pos,
        current_position=Position(8, 10),
        enemies=enemies,
        map_width=60,
        map_height=60,
        grid=grid,
        my_team=1,
        actor_id=7,
        profile=profile,
    )

    assert sites
    assert profile["assault_threat_score_calls"] > 0
    assert profile["assault_threat_filter_source_enemies"] == len(enemies)
    assert profile["assault_threat_filter_candidates"] == 0
    assert profile["assault_threat_enemy_scans"] == 0


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


def test_is_passable_uses_building_team_for_core_tiles():
    class _CorePassabilityController:
        def __init__(self, core_team: int) -> None:
            self.core_team = core_team

        def get_map_width(self):
            return 5

        def get_map_height(self):
            return 5

        def get_tile_building_id(self, pos):
            return 77 if pos == Position(1, 0) else None

        def get_entity_type(self, entity_id):
            assert entity_id == 77
            return EntityType.CORE

        def get_team(self, entity_id=None):
            if entity_id is None:
                return 1
            return self.core_team

        def get_tile_env(self, _pos):
            return Environment.EMPTY

    bot = SimpleNamespace(
        grid={
            (1, 0): {
                "building": EntityType.CORE,
                "building_team": 1,
                "entity_team": None,
            }
        }
    )
    assert utils.is_passable(
        bot,
        _CorePassabilityController(core_team=1),
        Position(0, 0),
        Direction.EAST,
    )

    bot.grid[(1, 0)]["building_team"] = 2
    assert not utils.is_passable(
        bot,
        _CorePassabilityController(core_team=2),
        Position(0, 0),
        Direction.EAST,
    )


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


def test_sentinel_prefers_core_before_single_logistics_when_no_turret_or_defender():
    controller = _GotAnyGrapesSentinelController()
    del controller.entities[13]
    del controller.entities[15]
    controller.legal_targets = {
        (data["position"].x, data["position"].y)
        for data in controller.entities.values()
    }

    SentinelBot().run(controller)

    assert controller.fired_at == Position(8, 5)


def test_sentinel_cuts_logistics_before_core_when_hijack_cluster_is_deeper():
    controller = _GotAnyGrapesSentinelController()
    del controller.entities[13]
    del controller.entities[15]
    controller.entities[16] = {
        "team": 2,
        "type": EntityType.CONVEYOR,
        "position": Position(5, 3),
        "hp": 15,
    }
    controller.legal_targets = {
        (data["position"].x, data["position"].y)
        for data in controller.entities.values()
    }

    SentinelBot().run(controller)

    assert controller.fired_at == Position(6, 4)


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


def test_gunner_runtime_rotates_toward_visible_core_when_not_facing_target():
    controller = _GotAnyGrapesSentinelController()
    controller.legal_targets = set()
    controller.rotated_to = None

    def get_entity_type(entity_id=None):
        if entity_id is None:
            return EntityType.GUNNER
        return controller.entities[entity_id]["type"]

    controller.get_entity_type = get_entity_type
    controller.can_rotate = lambda direction: direction == Direction.EAST
    controller.rotate = lambda direction: setattr(controller, "rotated_to", direction)

    SentinelBot().run(controller)

    assert controller.fired_at is None
    assert controller.rotated_to == Direction.EAST


def test_player_instantiates_turret_runtime_for_gunner():
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.GUNNER,
        get_team=lambda _entity_id=None: 1,
        get_nearby_entities=lambda: [],
    )
    player = got_any_grapes_main.Player()

    player.run(controller)

    assert isinstance(player.robot, SentinelBot)


class _RushCoreController:
    def __init__(self) -> None:
        self.self_team = 1
        self.self_position = Position(5, 4)
        self.current_round = 40
        self.entities = {
            1: {
                "team": 1,
                "type": EntityType.CORE,
                "position": Position(1, 1),
            },
            2: {
                "team": 2,
                "type": EntityType.CORE,
                "position": Position(8, 5),
            },
        }
        self.built = []

    def get_current_round(self):
        return self.current_round

    def get_team(self, entity_id=None):
        if entity_id is None:
            return self.self_team
        return self.entities[entity_id]["team"]

    def get_position(self, entity_id=None):
        if entity_id is None:
            return self.self_position
        return self.entities[entity_id]["position"]

    def get_nearby_units(self):
        return list(self.entities)

    def get_entity_type(self, entity_id=None):
        if entity_id is None:
            return EntityType.BUILDER_BOT
        return self.entities[entity_id]["type"]

    def get_map_width(self):
        return 10

    def get_map_height(self):
        return 10

    def is_in_vision(self, _position):
        return True

    def can_fire_from(self, position, direction, turret_type, target):
        return (
            position == Position(6, 5)
            and direction == Direction.EAST
            and turret_type == EntityType.SENTINEL
            and target == Position(8, 5)
        )

    def can_build_gunner(self, _position, _direction):
        return False

    def build_gunner(self, position, direction):
        self.built.append(("gunner", position, direction))

    def can_build_sentinel(self, position, direction):
        return position == Position(6, 5) and direction == Direction.EAST

    def build_sentinel(self, position, direction):
        self.built.append(("sentinel", position, direction))


def test_rush_builds_visible_core_firing_sentinel_and_falls_back_to_assault():
    controller = _RushCoreController()
    bot = SimpleNamespace(
        core_pos=Position(1, 1),
        builder_mode=BuilderMode.RUSH,
        is_rush_builder=True,
        rush_target_core_pos=None,
        rush_turret_pos=None,
        rush_build_stance=None,
        rush_turret_type=None,
        rush_turret_direction=None,
        rush_symmetry_candidates=None,
        rush_failed_candidates=set(),
        rush_turret_built=False,
        visible_positions={(5, 4), (6, 5), (8, 5)},
        grid={
            (5, 4): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 5): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 4): {
                "last_seen": 40,
                "building": EntityType.HARVESTER,
                "building_team": 2,
                "env": Environment.ORE_TITANIUM,
            },
            (8, 5): {
                "last_seen": 40,
                "building": EntityType.CORE,
                "building_team": 2,
                "env": Environment.EMPTY,
            },
        },
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )

    def stop_rushing(fallback=BuilderMode.ASSAULTING):
        bot.is_rush_builder = False
        bot.builder_mode = fallback

    bot.stop_rushing = stop_rushing

    mode_rush.execute(bot, controller)

    assert controller.built == [("sentinel", Position(6, 5), Direction.EAST)]
    assert bot.rush_turret_built is True
    assert bot.is_rush_builder is False
    assert bot.builder_mode == BuilderMode.ASSAULTING


def test_rush_prefers_supply_fed_gunner_for_visible_core_fire():
    controller = _RushCoreController()
    controller.can_fire_from = lambda pos, direction, turret_type, target: (
        pos == Position(6, 5)
        and direction == Direction.EAST
        and turret_type == EntityType.GUNNER
        and target == Position(8, 5)
    )
    controller.can_build_gunner = (
        lambda position, direction: position == Position(6, 5)
        and direction == Direction.EAST
    )
    bot = SimpleNamespace(
        core_pos=Position(1, 1),
        builder_mode=BuilderMode.RUSH,
        is_rush_builder=True,
        rush_target_core_pos=None,
        rush_turret_pos=None,
        rush_build_stance=None,
        rush_turret_type=None,
        rush_turret_direction=None,
        rush_symmetry_candidates=None,
        rush_failed_candidates=set(),
        rush_turret_built=False,
        visible_positions={(5, 4), (6, 5), (6, 4), (8, 5)},
        grid={
            (5, 4): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 5): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 4): {
                "last_seen": 40,
                "building": EntityType.HARVESTER,
                "building_team": 2,
                "env": Environment.ORE_TITANIUM,
            },
            (8, 5): {
                "last_seen": 40,
                "building": EntityType.CORE,
                "building_team": 2,
                "env": Environment.EMPTY,
            },
        },
        connected_friendly_conveyors={},
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    bot.stop_rushing = lambda fallback=BuilderMode.ASSAULTING: setattr(
        bot,
        "is_rush_builder",
        False,
    ) or setattr(bot, "builder_mode", fallback)

    mode_rush.execute(bot, controller)

    assert controller.built == [("gunner", Position(6, 5), Direction.EAST)]
    assert bot.rush_turret_built is True
    assert bot.is_rush_builder is False


def test_rush_uses_enemy_transport_directed_into_core_fire_site():
    controller = _RushCoreController()
    controller.can_fire_from = lambda pos, direction, turret_type, target: (
        pos == Position(6, 5)
        and direction == Direction.EAST
        and turret_type == EntityType.GUNNER
        and target == Position(8, 5)
    )
    controller.can_build_gunner = (
        lambda position, direction: position == Position(6, 5)
        and direction == Direction.EAST
    )
    bot = SimpleNamespace(
        core_pos=Position(1, 1),
        builder_mode=BuilderMode.RUSH,
        is_rush_builder=True,
        rush_target_core_pos=None,
        rush_turret_pos=None,
        rush_build_stance=None,
        rush_turret_type=None,
        rush_turret_direction=None,
        rush_symmetry_candidates=None,
        rush_failed_candidates=set(),
        rush_turret_built=False,
        visible_positions={(5, 4), (6, 4), (6, 5), (8, 5)},
        grid={
            (5, 4): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 4): {
                "last_seen": 40,
                "building": EntityType.CONVEYOR,
                "building_team": 2,
                "building_dir": Direction.SOUTH,
                "env": Environment.EMPTY,
            },
            (6, 5): {"last_seen": 40, "env": Environment.EMPTY},
            (8, 5): {
                "last_seen": 40,
                "building": EntityType.CORE,
                "building_team": 2,
                "env": Environment.EMPTY,
            },
        },
        connected_friendly_conveyors={},
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    bot.stop_rushing = lambda fallback=BuilderMode.ASSAULTING: setattr(
        bot,
        "is_rush_builder",
        False,
    ) or setattr(bot, "builder_mode", fallback)

    mode_rush.execute(bot, controller)

    assert controller.built == [("gunner", Position(6, 5), Direction.EAST)]
    assert bot.rush_turret_built is True
    assert bot.is_rush_builder is False


def test_rush_refuses_unsupplied_core_fire_site(monkeypatch):
    controller = _RushCoreController()
    moves = []
    monkeypatch.setattr(
        mode_rush.navigation,
        "move_towards",
        lambda _bot, _ct, pos: moves.append(pos),
    )
    bot = SimpleNamespace(
        core_pos=Position(1, 1),
        builder_mode=BuilderMode.RUSH,
        is_rush_builder=True,
        rush_target_core_pos=None,
        rush_turret_pos=None,
        rush_build_stance=None,
        rush_turret_type=None,
        rush_turret_direction=None,
        rush_symmetry_candidates=None,
        rush_failed_candidates=set(),
        rush_turret_built=False,
        visible_positions={(5, 4), (6, 5), (8, 5)},
        grid={
            (5, 4): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 5): {"last_seen": 40, "env": Environment.EMPTY},
            (8, 5): {
                "last_seen": 40,
                "building": EntityType.CORE,
                "building_team": 2,
                "env": Environment.EMPTY,
            },
        },
        connected_friendly_conveyors={},
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    mode_rush.execute(bot, controller)

    assert controller.built == []
    assert moves == [Position(8, 5)]


def test_rush_refuses_misdirected_enemy_transport_as_core_fire_supply(monkeypatch):
    controller = _RushCoreController()
    controller.can_fire_from = lambda pos, direction, turret_type, target: (
        pos == Position(6, 5)
        and direction == Direction.EAST
        and turret_type == EntityType.GUNNER
        and target == Position(8, 5)
    )
    controller.can_build_gunner = (
        lambda position, direction: position == Position(6, 5)
        and direction == Direction.EAST
    )
    moves = []
    monkeypatch.setattr(
        mode_rush.navigation,
        "move_towards",
        lambda _bot, _ct, pos: moves.append(pos),
    )
    bot = SimpleNamespace(
        core_pos=Position(1, 1),
        builder_mode=BuilderMode.RUSH,
        is_rush_builder=True,
        rush_target_core_pos=None,
        rush_turret_pos=None,
        rush_build_stance=None,
        rush_turret_type=None,
        rush_turret_direction=None,
        rush_symmetry_candidates=None,
        rush_failed_candidates=set(),
        rush_turret_built=False,
        visible_positions={(5, 4), (6, 4), (6, 5), (8, 5)},
        grid={
            (5, 4): {"last_seen": 40, "env": Environment.EMPTY},
            (6, 4): {
                "last_seen": 40,
                "building": EntityType.CONVEYOR,
                "building_team": 2,
                "building_dir": Direction.EAST,
                "env": Environment.EMPTY,
            },
            (6, 5): {"last_seen": 40, "env": Environment.EMPTY},
            (8, 5): {
                "last_seen": 40,
                "building": EntityType.CORE,
                "building_team": 2,
                "env": Environment.EMPTY,
            },
        },
        connected_friendly_conveyors={},
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )

    mode_rush.execute(bot, controller)

    assert controller.built == []
    assert moves == [Position(8, 5)]


def test_rush_clears_enemy_core_logistics_underfoot_before_turret_plan():
    controller = _RushCoreController()
    fired = []
    controller.can_fire = lambda pos: pos == Position(5, 4)
    controller.fire = lambda pos: fired.append(pos)
    bot = SimpleNamespace(
        core_pos=Position(1, 1),
        builder_mode=BuilderMode.RUSH,
        is_rush_builder=True,
        rush_target_core_pos=None,
        rush_turret_pos=None,
        rush_build_stance=None,
        rush_turret_type=None,
        rush_turret_direction=None,
        rush_symmetry_candidates=None,
        rush_failed_candidates=set(),
        rush_turret_built=False,
        visible_positions={(5, 4), (8, 5)},
        grid={
            (5, 4): {
                "last_seen": 40,
                "building": EntityType.CONVEYOR,
                "building_team": 2,
                "building_dir": Direction.EAST,
                "env": Environment.EMPTY,
            },
            (8, 5): {
                "last_seen": 40,
                "building": EntityType.CORE,
                "building_team": 2,
                "env": Environment.EMPTY,
            },
        },
        connected_friendly_conveyors={},
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )

    mode_rush.execute(bot, controller)

    assert fired == [Position(5, 4)]
    assert controller.built == []


def test_bonus_diagonal_builder_starts_in_rush_mode_after_gate():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(11, 9)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: builder_bot.RUSH_ASSIGNMENT_MIN_ROUND,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is True
    assert bot.is_rush_builder is True
    assert bot.builder_mode == BuilderMode.RUSH


def test_builder_init_ignores_enemy_core_when_caching_home_core():
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    controller = SimpleNamespace(
        get_position=lambda _entity_id=None: Position(17, 17)
        if _entity_id == 99
        else Position(16, 16),
        get_team=lambda _entity_id=None: 1 if _entity_id is None else 2,
        get_nearby_entities=lambda: [99],
        get_entity_type=lambda _entity_id: EntityType.CORE,
        get_current_round=lambda: 100,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.core_pos is None
    assert bot.is_assault_role is False


def test_opening_center_diagonal_builder_becomes_core_rusher():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    # Core at (10,10) on 40x40: physical center is southeast, so the
    # opening rusher is the SE diagonal.
    bot.spawn_pos = Position(11, 11)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 6,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is True
    assert bot.is_core_rusher is True
    assert bot.is_rush_builder is True
    assert bot.builder_mode == BuilderMode.RUSH


def test_late_center_diagonal_spawn_still_becomes_core_rusher():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(11, 11)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: builder_bot.OPENING_ROLE_MAX_SPAWN_ROUND + 20,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is True
    assert bot.is_core_rusher is True
    assert bot.is_rush_builder is True
    assert bot.builder_mode == BuilderMode.RUSH


def test_cardinal_north_spawn_is_plain_ore_finder():
    # Core at (10,10) on a 40x40 map (center 20,20). Centerward cardinal
    # from the core is EAST (dx=10 >= dy=10, ties favor EAST). NORTH is
    # therefore a plain ore finder.
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(10, 9)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 3,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is False
    assert bot.is_defender_role is False
    assert bot.is_rush_builder is False
    assert bot.spawn_slot is None
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_cardinal_south_spawn_is_plain_ore_finder():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(10, 11)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 3,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is False
    assert bot.is_defender_role is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_cardinal_east_spawn_becomes_defender():
    # Core at (10,10) on 40x40 map — centerward is EAST, so EAST spawn
    # is the defender slot.
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(11, 10)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 3,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_defender_role is True
    assert bot.is_assault_role is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_cardinal_west_spawn_becomes_defender_when_centerward():
    # Mirror-image case: core at (30,10) on 40x40, center is at (20,20).
    # Centerward from the core is WEST (dx=-10, |dx|>=|dy|=10). This
    # test locks the new symmetry-aware defender assignment so TEAM_B
    # (lower-right core) gets a defender facing the interior.
    bot = BuilderBot()
    bot.core_pos = Position(30, 10)
    bot.spawn_pos = Position(29, 10)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 3,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_defender_role is True
    assert bot.is_assault_role is False
    assert bot.is_core_rusher is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_cardinal_west_spawn_stays_plain_economy_when_not_centerward():
    # Core at (10,10) on 40x40 — centerward is EAST, so WEST is NOT
    # the defender and should stay a plain ore finder.
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(9, 10)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 3,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is False
    assert bot.is_defender_role is False
    assert bot.is_rush_builder is False
    assert bot.is_core_rusher is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_late_cardinal_east_spawn_stays_economy_builder():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(11, 10)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: builder_bot.OPENING_ROLE_MAX_SPAWN_ROUND + 1,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_defender_role is False
    assert bot.is_assault_role is False
    assert bot.is_core_rusher is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_late_cardinal_west_spawn_stays_economy_builder():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(9, 10)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: builder_bot.OPENING_ROLE_MAX_SPAWN_ROUND + 1,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_defender_role is False
    assert bot.is_assault_role is False
    assert bot.is_core_rusher is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_choose_best_visible_assault_site_core_rusher_breaks_ties_toward_core():
    """When core_rusher_anchor is provided, the visible-site picker
    uses `core_dist` as a TIEBREAKER after the strategic primaries
    (commit stickiness, surround progress, useful shot, threatened
    state, reachability). If two candidate harvesters are equivalent
    on the primaries (same manhattan to the rusher, same site shape)
    but differ in distance-to-enemy-core, the picker should prefer
    the harvester whose ring sits closer to the core anchor.

    Two symmetric harvesters are placed equidistantly from the
    rusher's position so the `manhattan(current, site.ring)` term
    ties and the `core_dist` tiebreaker decides.
    """
    # Rusher at (20, 20); two harvesters both 5 tiles away on the
    # x-axis so manhattan ties.
    enemies = [
        assault.VisibleEnemy(Position(15, 20), EntityType.HARVESTER),
        assault.VisibleEnemy(Position(25, 20), EntityType.HARVESTER),
    ]

    grid = {
        (15, 20): {"env": Environment.ORE_TITANIUM, "building": EntityType.HARVESTER, "building_team": 2},
        (25, 20): {"env": Environment.ORE_TITANIUM, "building": EntityType.HARVESTER, "building_team": 2},
    }
    for x in range(50):
        for y in range(50):
            if (x, y) in grid:
                continue
            grid[(x, y)] = {"env": Environment.EMPTY, "building": None}

    site_east_core = assault.choose_best_visible_assault_site(
        current_position=Position(20, 20),
        enemies=enemies,
        map_width=50,
        map_height=50,
        grid=grid,
        my_team=1,
        actor_id=42,
        core_rusher_anchor=Position(40, 20),
    )
    assert site_east_core is not None
    # Enemy core anchor is to the east; the east harvester ring is
    # closer to it, so the tiebreaker should pick the east one.
    assert site_east_core.harvester_position == Position(25, 20)

    site_west_core = assault.choose_best_visible_assault_site(
        current_position=Position(20, 20),
        enemies=enemies,
        map_width=50,
        map_height=50,
        grid=grid,
        my_team=1,
        actor_id=42,
        core_rusher_anchor=Position(0, 20),
    )
    assert site_west_core is not None
    # Flipping the core anchor to the west should flip the choice.
    assert site_west_core.harvester_position == Position(15, 20)


def test_defender_ore_target_fallback_does_not_enter_exploring(monkeypatch):
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(11, 10)
    bot.is_defender_role = True
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.pathfinding_state = {
        "known_obstacles": set(),
        "temporary_obstacles": {},
        "planner_state": None,
    }
    calls = []

    def _no_target(*_args, **_kwargs):
        return None

    monkeypatch.setattr(mode_finding_ore, "_find_best_ore_target", _no_target)
    monkeypatch.setattr(
        mode_finding_ore,
        "_find_disconnected_harvester_to_retile",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        mode_exploring,
        "execute",
        lambda *a, **k: calls.append("exploring"),
    )

    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_position=lambda *_a: Position(11, 10),
    )

    mode_finding_ore.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert calls == []


def test_mode_subphase_profile_disabled_does_not_call_time(monkeypatch):
    def fail_time_ns():
        raise AssertionError("disabled subphase profiling should not read time")

    monkeypatch.setattr(utils, "DEBUG_TURN_PROFILE", False)
    monkeypatch.setattr(mode_finding_ore.time, "time_ns", fail_time_ns)
    monkeypatch.setattr(mode_exploring.time, "time_ns", fail_time_ns)
    monkeypatch.setattr(
        mode_finding_ore,
        "_find_disconnected_harvester_to_retile",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mode_finding_ore,
        "_find_best_ore_target",
        lambda *_args, **_kwargs: None,
    )

    finding_bot = SimpleNamespace(
        ore_target_blacklist={},
        claimed_harvesters=set(),
        is_defender_role=True,
        builder_mode=BuilderMode.FINDING_ORE,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        turn_profile={},
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_position=lambda *_args: Position(11, 10),
    )

    mode_finding_ore.execute(finding_bot, controller)

    assert finding_bot.turn_profile == {}

    monkeypatch.setattr(navigation, "move_towards", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        navigation,
        "consume_shared_progress_stall",
        lambda *_args, **_kwargs: False,
    )
    exploring_bot = SimpleNamespace(
        all_map_chunks=[(0, 0)],
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks=set(),
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=(0, 0),
        explore_target_pos=Position(1, 1),
        explore_stuck_turns=0,
        titanium_locations=set(),
        axionite_locations=set(),
        grid={},
        builder_mode=BuilderMode.EXPLORING,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        turn_profile={},
    )
    exploring_controller = SimpleNamespace(
        get_map_width=lambda: 16,
        get_map_height=lambda: 16,
        get_position=lambda *_args: Position(0, 0),
        get_team=lambda *_args: 1,
        get_current_round=lambda: 20,
    )

    mode_exploring.execute(exploring_bot, exploring_controller)

    assert exploring_bot.turn_profile == {}


def test_finding_ore_subphase_profile_records_move_path(monkeypatch):
    monkeypatch.setattr(utils, "DEBUG_TURN_PROFILE", True)
    ticks = iter(range(1_000, 10_000, 100))
    monkeypatch.setattr(mode_finding_ore.time, "time_ns", lambda: next(ticks))

    def bump_profile(bot, key, value=1):
        bot.turn_profile[key] = bot.turn_profile.get(key, 0) + value

    monkeypatch.setattr(utils, "bump_profile", bump_profile)
    monkeypatch.setattr(
        mode_finding_ore,
        "_find_disconnected_harvester_to_retile",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mode_finding_ore,
        "_find_best_ore_target",
        lambda *_args, **_kwargs: (Position(5, 5), Position(4, 5), 10),
    )
    monkeypatch.setattr(mode_finding_ore, "_share_ore_marker", lambda *_args: None)
    monkeypatch.setattr(navigation, "move_towards", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        navigation,
        "consume_shared_progress_stall",
        lambda *_args, **_kwargs: False,
    )
    progress_calls = []
    monkeypatch.setattr(
        mode_finding_ore,
        "_note_ore_target_progress",
        lambda *_args, **_kwargs: progress_calls.append(True),
    )

    bot = SimpleNamespace(
        ore_target_blacklist={},
        claimed_harvesters=set(),
        is_defender_role=False,
        builder_mode=BuilderMode.FINDING_ORE,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        turn_profile={},
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_position=lambda *_args: Position(0, 0),
    )

    mode_finding_ore.execute(bot, controller)

    assert progress_calls == [True]
    for key in (
        "finding_blacklist_ns",
        "finding_recheck_claims_ns",
        "finding_retile_scan_ns",
        "finding_best_target_ns",
        "finding_share_marker_ns",
        "finding_move_nav_ns",
        "finding_progress_note_ns",
    ):
        assert bot.turn_profile[key] > 0


def test_exploring_subphase_profile_records_successful_move(monkeypatch):
    monkeypatch.setattr(utils, "DEBUG_TURN_PROFILE", True)
    ticks = iter(range(1_000, 10_000, 100))
    monkeypatch.setattr(mode_exploring.time, "time_ns", lambda: next(ticks))

    def bump_profile(bot, key, value=1):
        bot.turn_profile[key] = bot.turn_profile.get(key, 0) + value

    monkeypatch.setattr(utils, "bump_profile", bump_profile)
    monkeypatch.setattr(navigation, "move_towards", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        navigation,
        "consume_shared_progress_stall",
        lambda *_args, **_kwargs: False,
    )

    bot = SimpleNamespace(
        all_map_chunks=[(0, 0)],
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks=set(),
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=(0, 0),
        explore_target_pos=Position(1, 1),
        explore_stuck_turns=0,
        titanium_locations=set(),
        axionite_locations=set(),
        grid={},
        builder_mode=BuilderMode.EXPLORING,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        turn_profile={},
    )
    controller = SimpleNamespace(
        get_map_width=lambda: 16,
        get_map_height=lambda: 16,
        get_position=lambda *_args: Position(0, 0),
        get_team=lambda *_args: 1,
        get_current_round=lambda: 20,
    )

    mode_exploring.execute(bot, controller)

    assert bot.explore_stuck_turns == 0
    for key in (
        "explore_setup_ns",
        "explore_clear_target_ns",
        "explore_nav_ns",
        "explore_progress_note_ns",
    ):
        assert bot.turn_profile[key] > 0


def test_defender_ignores_ore_outside_core_l1_shell():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.is_defender_role = True
    bot.titanium_locations = {Position(20, 10)}
    bot.axionite_locations = set()
    bot.grid = {}
    bot.claimed_harvesters = set()
    bot.bot_locations = set()
    bot.ore_target_blacklist = {}
    bot.pathfinding_state = {"known_obstacles": set()}
    controller = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
        get_global_resources=lambda: (0, 0),
    )

    assert mode_finding_ore._find_best_ore_target_euclidean(  # noqa: SLF001
        bot,
        controller,
    ) is None


def test_defender_can_service_ore_inside_core_l1_shell():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.is_defender_role = True
    bot.titanium_locations = {Position(15, 10)}
    bot.axionite_locations = set()
    bot.grid = {}
    bot.claimed_harvesters = set()
    bot.bot_locations = set()
    bot.ore_target_blacklist = {}
    bot.pathfinding_state = {"known_obstacles": set()}
    controller = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
        get_global_resources=lambda: (0, 0),
    )

    target = mode_finding_ore._find_best_ore_target_euclidean(  # noqa: SLF001
        bot,
        controller,
    )

    assert target is not None
    assert target[0] == Position(15, 10)
    assert target[1] == Position(14, 10)


def test_bfs_ore_target_does_not_use_ore_tile_as_access():
    bot = SimpleNamespace(
        titanium_locations={Position(1, 1), Position(2, 1)},
        axionite_locations=set(),
        grid={
            (1, 1): {"env": Environment.ORE_TITANIUM},
            (2, 1): {"env": Environment.ORE_TITANIUM},
            (2, 0): {"env": Environment.EMPTY},
            (2, 2): {"env": Environment.EMPTY},
            (3, 1): {"env": Environment.EMPTY},
        },
        claimed_harvesters={(1, 1)},
        bot_locations=set(),
        ore_target_blacklist={},
        is_defender_role=False,
        pathfinding_state={
            "known_obstacles": {(1, 1), (2, 1)},
        },
        connected_friendly_conveyors={},
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(0, 1),
        get_current_round=lambda: 20,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 6,
        get_map_height=lambda: 5,
        get_global_resources=lambda: (0, 0),
    )

    target = mode_finding_ore._find_best_ore_target(  # noqa: SLF001
        bot,
        controller,
        max_bfs_nodes=16,
    )

    assert target is not None
    ore_pos, access_pos, _ = target
    assert ore_pos == Position(2, 1)
    assert access_pos not in bot.titanium_locations
    assert utils.manhattan(ore_pos, access_pos) == 1


def test_ore_friend_claim_uses_supplied_access_cache(monkeypatch):
    bot = SimpleNamespace(bot_locations={(4, 5)})
    controller = SimpleNamespace(get_position=lambda: Position(1, 5))
    cache = {}
    seen_cache_ids = []

    def fake_access(_bot, _ct, ore_pos, from_pos, access_cache):
        seen_cache_ids.append(id(access_cache))
        key = (ore_pos.x, ore_pos.y, from_pos.x, from_pos.y)
        access_cache[key] = Position(ore_pos.x - 1, ore_pos.y)
        return access_cache[key]

    monkeypatch.setattr(mode_finding_ore, "_cached_access_point", fake_access)

    claimed = mode_finding_ore._is_ore_claimed_by_friend(  # noqa: SLF001
        bot,
        controller,
        Position(5, 5),
        cache,
    )

    assert claimed is True
    assert seen_cache_ids == [id(cache), id(cache)]
    assert len(cache) == 2


def test_bfs_ore_target_passes_access_cache_to_friend_claim(monkeypatch):
    bot = SimpleNamespace(
        titanium_locations={Position(2, 1)},
        axionite_locations=set(),
        grid={(2, 1): {"env": Environment.ORE_TITANIUM}},
        claimed_harvesters=set(),
        bot_locations=set(),
        ore_target_blacklist={},
        is_defender_role=False,
        pathfinding_state={"known_obstacles": {(2, 1)}},
        connected_friendly_conveyors={},
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(0, 1),
        get_current_round=lambda: 20,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 6,
        get_map_height=lambda: 5,
        get_global_resources=lambda: (0, 0),
    )
    seen_cache_present = []

    def fake_claim(_bot, _ct, _ore_pos, access_cache=None):
        seen_cache_present.append(access_cache is not None)
        return False

    monkeypatch.setattr(mode_finding_ore, "_is_ore_claimed_by_friend", fake_claim)

    target = mode_finding_ore._find_best_ore_target(  # noqa: SLF001
        bot,
        controller,
        max_bfs_nodes=16,
    )

    assert target is not None
    assert seen_cache_present == [True]


def test_defender_leashes_back_to_l1_core_shell(monkeypatch):
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.is_defender_role = True
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.visible_enemy_targets = []
    moves = []
    monkeypatch.setattr(
        builder_bot.navigation,
        "move_towards",
        lambda _bot, _ct, target: moves.append(target),
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(20, 10),
        get_current_round=lambda: 10,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    assert bot._maybe_defender_hold_or_leash(controller) is True  # noqa: SLF001

    assert moves == [Position(15, 10)]


def test_builder_run_checks_core_guard_before_defender_leash(monkeypatch):
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.spawn_pos = Position(20, 10)
    bot.spawn_round = 20
    bot.is_assault_role = False
    bot.is_defender_role = True
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.visible_enemy_targets = []
    calls = []

    monkeypatch.setattr(
        builder_bot.perception,
        "scan_around",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        builder_bot.defense,
        "core_port_guard_if_needed",
        lambda *_args, **_kwargs: calls.append("core_guard") or True,
    )
    monkeypatch.setattr(
        builder_bot.defense,
        "defend_core_if_needed",
        lambda *_args, **_kwargs: calls.append("core_defense") or False,
    )
    monkeypatch.setattr(
        builder_bot.navigation,
        "move_towards",
        lambda *_args, **_kwargs: calls.append("leash"),
    )

    controller = SimpleNamespace(
        get_current_round=lambda: 20,
        get_position=lambda: Position(20, 10),
        get_id=lambda: 99,
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
    )

    bot.run(controller)

    assert calls == ["core_guard"]


def test_defender_tiling_back_can_answer_core_threat():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.is_defender_role = True
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(12, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
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


def test_non_defender_tiling_back_still_skips_non_emergency_core_defense():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.is_defender_role = False
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    bot.grid = {}
    bot.connected_friendly_conveyors = {}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda *_args: calls.append("sentinel?") or True,
        build_sentinel=lambda *_args: calls.append("sentinel"),
        get_global_resources=lambda: (10_000, 0),
    )

    assert defense.defend_core_if_needed(bot, controller) is False
    assert calls == []


def test_non_defender_tiling_back_answers_emergency_core_threat_with_supply():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.is_defender_role = False
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(12, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    bot.grid = {
        (12, 12): {
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        },
    }
    bot.connected_friendly_conveyors = {(12, 12): 1}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda pos, _direction: pos == Position(12, 11),
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
        get_global_resources=lambda: (0, 0),
    )

    assert defense.defend_core_if_needed(bot, controller) is True
    assert len(built) == 1
    assert built[0][0] == Position(12, 11)


def test_non_defender_tiling_builder_does_not_leash(monkeypatch):
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.is_defender_role = False
    bot.builder_mode = BuilderMode.TILING_BACK
    moves = []
    monkeypatch.setattr(
        builder_bot.navigation,
        "move_towards",
        lambda _bot, _ct, target: moves.append(target),
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(20, 10),
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    assert bot._maybe_defender_hold_or_leash(controller) is False  # noqa: SLF001
    assert moves == []


def test_defender_inside_l1_core_shell_does_not_leash():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.is_defender_role = True
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.visible_enemy_targets = []
    controller = SimpleNamespace(get_position=lambda: Position(13, 12), get_team=lambda *_a: "A", get_current_round=lambda: 10)

    assert bot._maybe_defender_hold_or_leash(controller) is False  # noqa: SLF001


def test_defender_allows_defense_hooks_when_enemy_visible():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.is_defender_role = True
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    controller = SimpleNamespace(get_position=lambda: Position(13, 12), get_team=lambda *_a: "A", get_current_round=lambda: 10)

    assert bot._maybe_defender_hold_or_leash(controller) is False  # noqa: SLF001


def test_non_rusher_opening_diagonal_stays_builder():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    # NE is not the center-facing rusher diagonal for this seat.
    bot.spawn_pos = Position(11, 9)
    controller = SimpleNamespace(
        get_entity_type=lambda _entity_id=None: EntityType.BUILDER_BOT,
        get_id=lambda: 7,
        get_current_round=lambda: 6,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    bot._init_turn(controller)  # noqa: SLF001

    assert bot.is_assault_role is False
    assert bot.is_rush_builder is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


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


def test_perception_scans_connected_harvester_marker():
    controller = _MarkerController(
        marker.create_connected_harvester_marker(
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

    assert bot.shared_connected_harvester_positions == {(11, 9)}


def _connected_refresh_bot(*, last_refresh_round: int, mode: BuilderMode):
    return SimpleNamespace(
        builder_mode=mode,
        core_pos=Position(0, 0),
        grid={
            (2, 1): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            },
        },
        visible_positions={(2, 1)},
        pathfinding_state={"known_obstacles": set()},
        known_friendly_conveyors=set(),
        connected_friendly_conveyors={},
        last_connected_refresh_round=last_refresh_round,
        titanium_locations=set(),
        axionite_locations=set(),
        bot_locations=set(),
        visible_friendly_builders=[],
        confirmed_enemy_harvesters={},
        harvester_anchor=None,
        tracked_harvesters={},
        known_harvesters={},
        claimed_harvesters=set(),
    )


def test_connected_refresh_updates_new_topology_incrementally():
    bot = _connected_refresh_bot(
        last_refresh_round=9,
        mode=BuilderMode.FINDING_ORE,
    )
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 12,
        get_position=lambda: Position(1, 1),
        get_id=lambda: 99,
    )

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        controller,
        nearby_units=[],
        nearby_cache={},
        refresh_connected=True,
    )

    assert bot.known_friendly_conveyors == {(2, 1)}
    assert bot.connected_friendly_conveyors == {(2, 1): 0}
    assert bot.last_connected_refresh_round == 12


def test_connected_incremental_update_does_not_scan_unrelated_known_conveyors():
    class _NoBroadScanGrid(dict):
        def get(self, key, default=None):
            if key == (20, 20):
                raise AssertionError("incremental update scanned unrelated conveyor")
            return super().get(key, default)

    bot = _connected_refresh_bot(
        last_refresh_round=9,
        mode=BuilderMode.FINDING_ORE,
    )
    bot.grid = _NoBroadScanGrid(bot.grid)
    bot.known_friendly_conveyors = {(20, 20)}
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 12,
        get_position=lambda: Position(1, 1),
        get_id=lambda: 99,
    )

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        controller,
        nearby_units=[],
        nearby_cache={},
        refresh_connected=True,
    )

    assert bot.connected_friendly_conveyors == {(2, 1): 0}
    assert bot.last_connected_refresh_round == 12


def test_connected_incremental_caches_marker_known_visible_transport():
    bot = _connected_refresh_bot(
        last_refresh_round=-100,
        mode=BuilderMode.FINDING_ORE,
    )
    bot.known_friendly_conveyors = {(2, 1)}
    bot.connected_friendly_conveyors = {(2, 1): 0}
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 12,
        get_position=lambda: Position(1, 1),
        get_id=lambda: 99,
    )

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        controller,
        nearby_units=[],
        nearby_cache={},
        refresh_connected=True,
    )

    assert bot.connected_forward_links == {(2, 1): (1, 1)}
    assert bot.connected_friendly_conveyors == {(2, 1): 0}
    assert bot.last_connected_refresh_round == 12


def test_connected_incremental_removal_invalidates_upstream_component():
    bot = _connected_refresh_bot(
        last_refresh_round=10,
        mode=BuilderMode.FINDING_ORE,
    )
    bot.grid[(3, 1)] = {
        "env": Environment.EMPTY,
        "building": EntityType.CONVEYOR,
        "building_team": 1,
        "building_dir": Direction.WEST,
    }
    bot.visible_positions = {(2, 1)}
    bot.known_friendly_conveyors = {(2, 1), (3, 1)}
    perception._refresh_connected_friendly_conveyors(bot, 1)  # noqa: SLF001
    assert set(bot.connected_friendly_conveyors) == {(2, 1), (3, 1)}

    bot.grid[(2, 1)] = {"env": Environment.EMPTY}
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 12,
        get_position=lambda: Position(1, 1),
        get_id=lambda: 99,
    )

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        controller,
        nearby_units=[],
        nearby_cache={},
        refresh_connected=True,
    )

    assert bot.known_friendly_conveyors == {(3, 1)}
    assert bot.connected_friendly_conveyors == {}


def test_connected_incremental_direction_change_invalidates_component():
    bot = _connected_refresh_bot(
        last_refresh_round=10,
        mode=BuilderMode.FINDING_ORE,
    )
    bot.visible_positions = {(2, 1)}
    bot.known_friendly_conveyors = {(2, 1)}
    perception._refresh_connected_friendly_conveyors(bot, 1)  # noqa: SLF001
    assert bot.connected_friendly_conveyors == {(2, 1): 0}

    bot.grid[(2, 1)]["building_dir"] = Direction.EAST
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 12,
        get_position=lambda: Position(1, 1),
        get_id=lambda: 99,
    )

    perception._infer_state_from_grid(  # noqa: SLF001
        bot,
        controller,
        nearby_units=[],
        nearby_cache={},
        refresh_connected=True,
    )

    assert bot.connected_forward_links == {(2, 1): (3, 1)}
    assert bot.connected_friendly_conveyors == {}


def test_connected_loads_aggregate_branch_sources_without_lane_walks():
    bot = SimpleNamespace(
        core_pos=Position(0, 0),
        grid={
            (2, 0): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            },
            (3, 0): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            },
            (2, 1): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.NORTH,
            },
        },
        known_friendly_conveyors={(2, 0), (3, 0), (2, 1)},
        connected_friendly_conveyors={},
        tracked_harvesters={
            (4, 0): 1,
            (2, 2): 1,
            (4, 2): 2,
        },
    )

    perception._refresh_connected_friendly_conveyors(bot, 1)  # noqa: SLF001

    assert bot.connected_friendly_conveyors == {
        (2, 0): 2,
        (3, 0): 2,
        (2, 1): 2,
    }


def test_connected_load_time_gate_keeps_membership_current():
    bot = SimpleNamespace(
        core_pos=Position(0, 0),
        grid={
            (2, 0): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.WEST,
            },
        },
        known_friendly_conveyors={(2, 0)},
        connected_friendly_conveyors={(99, 99): 7},
        tracked_harvesters={(3, 0): 1},
        timing_governor=SimpleNamespace(has_budget_for=lambda *_args: False),
    )

    perception._refresh_connected_friendly_conveyors(bot, 1)  # noqa: SLF001

    assert bot.connected_friendly_conveyors == {(2, 0): 0}


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


def test_fast_perception_reuses_cached_building_metadata():
    calls = {"type": 0, "team": 0, "direction": 0, "hp": 0, "max_hp": 0}

    class _FastIdCacheController:
        def get_team(self, entity_id=None):
            if entity_id is None:
                return 1
            calls["team"] += 1
            return 1

        def get_id(self):
            return 7

        def get_current_round(self):
            return 11

        def get_position(self, entity_id=None):
            return Position(0, 0)

        def get_map_width(self):
            return 20

        def get_map_height(self):
            return 20

        def get_nearby_tiles(self, radius_sq=None):
            assert radius_sq == perception.FAST_SCAN_RADIUS_SQ
            return [Position(0, 0)]

        def get_tile_env(self, pos):
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            return 42

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            calls["type"] += 1
            return EntityType.CONVEYOR

        def get_direction(self, entity_id):
            calls["direction"] += 1
            return Direction.EAST

        def get_bridge_target(self, entity_id):
            raise AssertionError("not a bridge")

        def get_hp(self, entity_id):
            calls["hp"] += 1
            return 20

        def get_max_hp(self, entity_id):
            calls["max_hp"] += 1
            return 20

    bot = BuilderBot()
    bot.grid = {
        (0, 0): {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_id": 42,
            "building_dir": Direction.EAST,
        },
    }

    perception._scan_local_fast(  # noqa: SLF001
        bot,
        _FastIdCacheController(),
        include_building_health=True,
    )

    assert calls["type"] == 0
    assert calls["team"] == 0
    assert calls["direction"] == 0
    assert calls["hp"] == 1
    assert calls["max_hp"] == 1
    assert bot.grid[(0, 0)]["building"] is EntityType.CONVEYOR
    assert bot.grid[(0, 0)]["building_dir"] is Direction.EAST


def test_snapshot_skips_friendly_passable_non_builder_position():
    my_team = "A"
    enemy_team = "B"
    unit_data = {
        100: (Position(1, 0), EntityType.CORE, my_team),
        200: (Position(2, 0), EntityType.SENTINEL, my_team),
        300: (Position(3, 0), EntityType.CORE, enemy_team),
    }
    position_calls = []

    def get_position(entity_id):
        position_calls.append(entity_id)
        if entity_id == 100:
            raise AssertionError("friendly passable non-builder position should be skipped")
        return unit_data[entity_id][0]

    controller = SimpleNamespace(
        get_team=lambda *args: my_team if not args else unit_data[args[0]][2],
        get_position=get_position,
        get_nearby_units=lambda: list(unit_data.keys()),
        get_tile_env=lambda _pos: Environment.EMPTY,
        get_tile_building_id=lambda _pos: None,
        get_entity_type=lambda entity_id: unit_data[entity_id][1],
        get_direction=lambda _entity_id: Direction.NORTH,
        get_bridge_target=lambda _entity_id: Position(0, 1),
        get_hp=lambda _entity_id: 1,
        get_max_hp=lambda _entity_id: 1,
    )
    bot = SimpleNamespace(grid={})

    _, _, nearby_units, nearby_cache = perception._collect_visible_snapshot(  # noqa: SLF001
        bot,
        controller,
        [Position(0, 0)],
        include_building_health=False,
    )

    assert 100 not in position_calls
    assert 100 not in nearby_cache
    assert 200 in nearby_units
    assert 300 in nearby_units
    assert set(position_calls) == {200, 300}


def test_fast_perception_skips_friendly_passable_non_builder_position():
    bot = BuilderBot()
    my_pos = Position(5, 5)
    my_team = "A"
    enemy_team = "B"
    unit_data = {
        100: (Position(6, 5), EntityType.CORE, my_team),
        200: (Position(4, 5), EntityType.BUILDER_BOT, my_team),
        300: (Position(7, 5), EntityType.CORE, enemy_team),
    }
    position_calls = []

    def get_position(*args):
        if not args:
            return my_pos
        entity_id = args[0]
        position_calls.append(entity_id)
        if entity_id == 100:
            raise AssertionError("friendly passable non-builder position should be skipped")
        return unit_data[entity_id][0]

    controller = SimpleNamespace(
        get_team=lambda *args: my_team if not args else unit_data[args[0]][2],
        get_id=lambda: 1,
        get_current_round=lambda: 20,
        get_position=get_position,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_nearby_tiles=lambda _radius_sq=None: [my_pos],
        get_tile_env=lambda _pos: Environment.EMPTY,
        get_tile_building_id=lambda _pos: None,
        get_nearby_units=lambda: list(unit_data.keys()),
        get_entity_type=lambda entity_id: unit_data[entity_id][1],
        get_direction=lambda _entity_id: Direction.NORTH,
        get_bridge_target=lambda _entity_id: Position(0, 1),
        get_hp=lambda _entity_id: 1,
        get_max_hp=lambda _entity_id: 1,
    )

    perception._scan_local_fast(  # noqa: SLF001
        bot,
        controller,
        include_building_health=False,
    )

    assert 100 not in position_calls
    assert set(position_calls) == {200, 300}
    assert (4, 5) in bot.bot_locations
    assert len(bot.visible_enemy_targets) == 1
    assert bot.visible_enemy_targets[0].position == Position(7, 5)


def test_fast_perception_keeps_friendly_blocking_turret_position():
    bot = BuilderBot()
    my_pos = Position(5, 5)
    turret_pos = Position(6, 5)
    unit_data = {
        100: (turret_pos, EntityType.SENTINEL, "A"),
    }
    position_calls = []

    def get_position(*args):
        if not args:
            return my_pos
        entity_id = args[0]
        position_calls.append(entity_id)
        return unit_data[entity_id][0]

    controller = SimpleNamespace(
        get_team=lambda *args: "A" if not args else unit_data[args[0]][2],
        get_id=lambda: 1,
        get_current_round=lambda: 20,
        get_position=get_position,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_nearby_tiles=lambda _radius_sq=None: [my_pos],
        get_tile_env=lambda _pos: Environment.EMPTY,
        get_tile_building_id=lambda _pos: None,
        get_nearby_units=lambda: list(unit_data.keys()),
        get_entity_type=lambda entity_id: unit_data[entity_id][1],
        get_direction=lambda _entity_id: Direction.NORTH,
        get_bridge_target=lambda _entity_id: Position(0, 1),
        get_hp=lambda _entity_id: 1,
        get_max_hp=lambda _entity_id: 1,
    )

    perception._scan_local_fast(  # noqa: SLF001
        bot,
        controller,
        include_building_health=False,
    )

    assert position_calls == [100]
    assert bot.grid[(turret_pos.x, turret_pos.y)]["entity"] is EntityType.SENTINEL
    assert (turret_pos.x, turret_pos.y) in bot.pathfinding_state["known_obstacles"]


def test_quiet_tiling_back_fast_perception_still_skips_health(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        perception,
        "_scan_local_fast",
        lambda _bot, _ct, *, include_building_health: captured.setdefault(
            "include_health",
            include_building_health,
        ),
    )
    bot = BuilderBot()
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.is_defender_role = False
    bot.visible_enemy_targets = []

    perception.scan_around(bot, SimpleNamespace(), fast=True, assault_mode=False)

    assert captured["include_health"] is False


def test_threatened_tiling_back_fast_perception_refreshes_health(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        perception,
        "_scan_local_fast",
        lambda _bot, _ct, *, include_building_health: captured.setdefault(
            "include_health",
            include_building_health,
        ),
    )
    bot = BuilderBot()
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.is_defender_role = False
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(2, 2), EntityType.BUILDER_BOT)
    ]

    perception.scan_around(bot, SimpleNamespace(), fast=True, assault_mode=False)

    assert captured["include_health"] is True


def test_defender_tiling_back_fast_perception_refreshes_health(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        perception,
        "_scan_local_fast",
        lambda _bot, _ct, *, include_building_health: captured.setdefault(
            "include_health",
            include_building_health,
        ),
    )
    bot = BuilderBot()
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.is_defender_role = True
    bot.visible_enemy_targets = []

    perception.scan_around(bot, SimpleNamespace(), fast=True, assault_mode=False)

    assert captured["include_health"] is True


def test_fast_perception_time_gates_marker_scan():
    calls = {"marker_value": 0}

    class _FastMarkerController:
        def get_team(self, entity_id=None):
            return 1

        def get_id(self):
            return 7

        def get_current_round(self):
            return 11

        def get_position(self, entity_id=None):
            return Position(0, 0)

        def get_map_width(self):
            return 20

        def get_map_height(self):
            return 20

        def get_nearby_tiles(self, radius_sq=None):
            return [Position(0, 0)]

        def get_tile_env(self, pos):
            return Environment.EMPTY

        def get_tile_building_id(self, pos):
            return 99

        def get_nearby_units(self):
            return []

        def get_entity_type(self, entity_id):
            return EntityType.MARKER

        def get_direction(self, entity_id):
            return Direction.NORTH

        def get_bridge_target(self, entity_id):
            return Position(0, 1)

        def get_hp(self, entity_id):
            return 1

        def get_max_hp(self, entity_id):
            return 1

        def get_marker_value(self, entity_id):
            calls["marker_value"] += 1
            raise AssertionError("marker scan should be skipped under budget pressure")

    bot = BuilderBot()
    bot.timing_governor = timing.TimingGovernor(
        started_ns=0,
        soft_deadline_ns=0,
        hard_deadline_ns=0,
    )

    perception._scan_local_fast(  # noqa: SLF001
        bot,
        _FastMarkerController(),
        include_building_health=False,
    )

    assert calls["marker_value"] == 0


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
    bot.connected_friendly_conveyors = {
        (4, 4): 1,
        (4, 5): 1,
        (4, 6): 1,
        (4, 7): 1,
    }
    expected_target = (Position(8, 8), Position(8, 9))

    import mode_hijacking  # noqa: E402

    monkeypatch.setattr(
        mode_hijacking,
        "find_visible_hijack_target",
        lambda _bot, _ct: expected_target,
    )
    controller = SimpleNamespace(get_global_resources=lambda: (100, 0))

    changed = bot._maybe_switch_to_hijack(controller)
    assert changed is True
    assert bot.builder_mode == BuilderMode.HIJACKING
    assert bot.hijack_source_pos == expected_target[0]
    assert bot.hijack_entry_pos == expected_target[1]


def test_builder_bot_does_not_switch_to_hijack_before_live_lane(monkeypatch):
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.connected_friendly_conveyors = {}

    monkeypatch.setattr(
        mode_hijacking,
        "find_visible_hijack_target",
        lambda *_args: (Position(8, 8), Position(8, 9)),
    )

    changed = bot._maybe_switch_to_hijack(SimpleNamespace())

    assert changed is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.hijack_source_pos is None
    assert bot.hijack_entry_pos is None


def test_builder_bot_does_not_switch_to_hijack_on_unsourced_core_stub(monkeypatch):
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.connected_friendly_conveyors = {
        (4, 4): 0,
        (4, 5): 0,
        (4, 6): 0,
        (4, 7): 0,
        (4, 8): 0,
    }

    monkeypatch.setattr(
        mode_hijacking,
        "find_visible_hijack_target",
        lambda *_args: (Position(8, 8), Position(8, 9)),
    )

    changed = bot._maybe_switch_to_hijack(
        SimpleNamespace(get_global_resources=lambda: (100, 0))
    )

    assert changed is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_builder_bot_does_not_switch_to_hijack_without_titanium_reserve(monkeypatch):
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.connected_friendly_conveyors = {
        (4, 4): 1,
        (4, 5): 1,
        (4, 6): 1,
        (4, 7): 1,
    }

    monkeypatch.setattr(
        mode_hijacking,
        "find_visible_hijack_target",
        lambda *_args: (Position(8, 8), Position(8, 9)),
    )

    changed = bot._maybe_switch_to_hijack(
        SimpleNamespace(get_global_resources=lambda: (0, 0))
    )

    assert changed is False
    assert bot.builder_mode == BuilderMode.FINDING_ORE


def test_exploration_deprioritizes_claimed_chunk_when_equivalent_unclaimed_exists():
    bot = SimpleNamespace(
        all_map_chunks=[(1, 0), (0, 1)],
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks={(1, 0)},
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=None,
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(0, 0),
        get_id=lambda: 1,
    )

    mode_exploring._select_optimal_unexplored_chunk(bot, controller, (0, 0))

    assert bot.explore_target_chunk == (0, 1)


def test_exploration_still_selects_least_bad_chunk_when_all_are_claimed():
    bot = SimpleNamespace(
        all_map_chunks=[(1, 0), (0, 1)],
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks={(1, 0), (0, 1)},
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=None,
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(0, 0),
        get_id=lambda: 1,
    )

    mode_exploring._select_optimal_unexplored_chunk(bot, controller, (0, 0))

    assert bot.explore_target_chunk in {(1, 0), (0, 1)}


def test_exploration_id_tiebreak_spreads_equal_distance_builders():
    chunks = [(1, 0), (0, 1)]
    bot_a = SimpleNamespace(
        all_map_chunks=chunks,
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks=set(),
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=None,
    )
    bot_b = SimpleNamespace(
        all_map_chunks=chunks,
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks=set(),
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=None,
    )

    mode_exploring._select_optimal_unexplored_chunk(
        bot_a,
        SimpleNamespace(get_position=lambda: Position(0, 0), get_id=lambda: 1),
        (0, 0),
    )
    mode_exploring._select_optimal_unexplored_chunk(
        bot_b,
        SimpleNamespace(get_position=lambda: Position(0, 0), get_id=lambda: 2),
        (0, 0),
    )

    assert {bot_a.explore_target_chunk, bot_b.explore_target_chunk} == set(chunks)


def test_exploration_chunk_target_avoids_known_blocked_center():
    chunk = (0, 0)
    center = mode_exploring._get_chunk_center(chunk, 16, 16)
    alternate = Position(center.x, center.y + 1)
    grid = {}
    for x in range(perception.CHUNK_SIZE):
        for y in range(perception.CHUNK_SIZE):
            grid[(x, y)] = {"env": Environment.WALL}
    grid[(alternate.x, alternate.y)] = {
        "env": Environment.EMPTY,
        "entity": None,
        "building": None,
    }
    bot = SimpleNamespace(grid=grid)
    controller = SimpleNamespace(
        get_map_width=lambda: 16,
        get_map_height=lambda: 16,
        get_position=lambda: Position(0, 0),
        get_team=lambda *_args: 1,
    )

    target = mode_exploring._get_chunk_target(bot, controller, chunk, 16, 16)

    assert target == alternate


def test_exploration_stall_retargets_chunk_before_blacklisting(monkeypatch):
    chunk = (0, 0)
    center = mode_exploring._get_chunk_center(chunk, 16, 16)
    alternate = Position(center.x, center.y + 1)
    grid = {}
    for x in range(perception.CHUNK_SIZE):
        for y in range(perception.CHUNK_SIZE):
            grid[(x, y)] = {"env": Environment.WALL}
    grid[(alternate.x, alternate.y)] = {
        "env": Environment.EMPTY,
        "entity": None,
        "building": None,
    }
    bot = SimpleNamespace(
        all_map_chunks=[chunk],
        explored_tiles=set(),
        unreachable_chunks=set(),
        claimed_explore_chunks=set(),
        bot_locations=[],
        core_pos=Position(0, 0),
        explore_target_chunk=chunk,
        explore_target_pos=center,
        explore_stuck_turns=mode_exploring.EXPLORE_STUCK_RETRY_TURNS - 1,
        titanium_locations=set(),
        axionite_locations=set(),
        grid=grid,
        builder_mode=BuilderMode.EXPLORING,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_map_width=lambda: 16,
        get_map_height=lambda: 16,
        get_position=lambda: Position(0, 0),
        get_team=lambda *_args: 1,
        get_current_round=lambda: 20,
    )
    monkeypatch.setattr(navigation, "move_towards", lambda *_args: False)
    monkeypatch.setattr(navigation, "consume_shared_progress_stall", lambda *_args: False)

    mode_exploring.execute(bot, controller)

    assert bot.explore_target_chunk == chunk
    assert bot.explore_target_pos == alternate
    assert bot.explore_stuck_turns == 0
    assert chunk not in bot.unreachable_chunks


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


def test_sentinel_supply_rejects_transport_not_directed_into_sentinel():
    bot = SimpleNamespace(
        grid={
            (12, 11): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
        },
        connected_friendly_conveyors={(12, 11): 1},
    )
    controller = SimpleNamespace(get_team=lambda *_args: 1)

    supply_class = defense._sentinel_supply_class(  # noqa: SLF001
        bot,
        controller,
        Position(12, 10),
    )

    assert supply_class == 99


def test_sentinel_supply_accepts_enemy_transport_directed_into_sentinel():
    bot = SimpleNamespace(
        grid={
            (12, 11): {
                "building": EntityType.CONVEYOR,
                "building_team": 2,
                "building_dir": Direction.NORTH,
            },
        },
        connected_friendly_conveyors={},
    )
    controller = SimpleNamespace(get_team=lambda *_args: 1)

    supply_class = defense._sentinel_supply_class(  # noqa: SLF001
        bot,
        controller,
        Position(12, 10),
    )

    assert supply_class == 0


def test_sentinel_supply_accepts_directed_friendly_transport_branch():
    bot = SimpleNamespace(
        grid={
            (12, 11): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.NORTH,
            },
        },
        connected_friendly_conveyors={},
    )
    controller = SimpleNamespace(get_team=lambda *_args: 1)

    supply_class = defense._sentinel_supply_class(  # noqa: SLF001
        bot,
        controller,
        Position(12, 10),
    )

    assert supply_class == 3


def test_defense_skips_sentinel_beside_unfed_connected_conveyor():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = set()
    bot.grid = {
        (12, 11): {
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.EAST,
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
        can_build_sentinel=lambda pos, _direction: pos == Position(12, 10),
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
        get_global_resources=lambda: (1000, 0),
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


def test_lane_defense_builds_fed_sentinel_for_adjacent_undamaged_builder():
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


def test_lane_defense_does_not_build_over_known_ore_tile():
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
        (16, 11): {
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.NORTH,
        },
    }
    bot.titanium_locations = {Position(16, 10)}
    bot.axionite_locations = set()
    bot.connected_friendly_conveyors = {(16, 11): 1}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    can_build_positions = []
    built = []

    controller = SimpleNamespace(
        get_position=lambda: Position(15, 10),
        get_current_round=lambda: 30,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_sentinel=lambda pos, _direction: can_build_positions.append(pos)
        or False,
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
        get_global_resources=lambda: (0, 0),
    )

    assert defense.defend_lane_if_needed(bot, controller) is False
    assert Position(16, 10) not in can_build_positions
    assert built == []


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


def test_core_port_guard_quiet_economy_noops():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = []
    bot.visible_positions = set()
    bot.grid = {}
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_team=lambda *_args: 1,
        can_fire=lambda *_args: calls.append("fire?") or True,
        can_heal=lambda *_args: calls.append("heal?") or True,
        can_build_barrier=lambda *_args: calls.append("barrier?") or True,
    )

    assert defense.core_port_guard_if_needed(bot, controller) is False
    assert calls == []


def test_core_port_guard_skips_assault_builder_with_enemy_core_as_core_pos():
    bot = BuilderBot()
    bot.is_assault_role = True
    bot.builder_mode = BuilderMode.ASSAULTING
    # Regression guard: assault builders can see the enemy core and older
    # init code can cache it as `core_pos`; home defense must not use that
    # stale/wrong anchor.
    bot.core_pos = Position(18, 18)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(16, 16), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(16, 18)}
    bot.grid = {
        (16, 18): {
            "env": Environment.EMPTY,
            "building": None,
            "entity": None,
        },
    }
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(17, 17),
        get_team=lambda *_args: 1,
        can_fire=lambda *_args: calls.append("fire?") or True,
        can_heal=lambda *_args: calls.append("heal?") or True,
        can_build_barrier=lambda *_args: calls.append("barrier?") or True,
    )

    assert defense.core_port_guard_if_needed(bot, controller) is False
    assert calls == []


def test_core_port_guard_heals_damaged_direct_core_port():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)}
    bot.grid = {
        (12, 10): {
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_hp": 6,
            "building_max_hp": 15,
        },
    }
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    healed = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda pos: pos == Position(12, 10),
        heal=lambda pos: healed.append(pos),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is True
    assert healed == [Position(12, 10)]
    assert bot.healing_this_turn is True


def test_core_port_guard_clears_hostile_logistics_underfoot():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)}
    bot.grid = {
        (12, 10): {
            "building": EntityType.ROAD,
            "building_team": 2,
        },
    }
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    fired = []

    controller = SimpleNamespace(
        get_position=lambda: Position(12, 10),
        get_team=lambda *_args: 1,
        can_fire=lambda pos: pos == Position(12, 10),
        fire=lambda pos: fired.append(pos),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is True
    assert fired == [Position(12, 10)]


def test_core_port_guard_blocks_isolated_open_gunner_site():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)}
    bot.grid = {
        (12, 10): {
            "env": Environment.EMPTY,
            "building": None,
            "entity": None,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.last_core_port_barrier_round = -9999
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    barriers = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
        can_build_barrier=lambda pos: pos == Position(12, 10),
        build_barrier=lambda pos: barriers.append(pos),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is True
    assert barriers == [Position(12, 10)]
    assert bot.last_core_port_barrier_round == 40


def test_core_port_guard_allows_tiling_back_builder_to_block_core_shell():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.TILING_BACK
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)}
    bot.grid = {
        (12, 10): {
            "env": Environment.EMPTY,
            "building": None,
            "entity": None,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.last_core_port_barrier_round = -9999
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    barriers = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
        can_build_barrier=lambda pos: pos == Position(12, 10),
        build_barrier=lambda pos: barriers.append(pos),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is True
    assert barriers == [Position(12, 10)]


def test_core_port_guard_respects_barrier_cooldown():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)}
    bot.grid = {
        (12, 10): {
            "env": Environment.EMPTY,
            "building": None,
            "entity": None,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.last_core_port_barrier_round = 35
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
        can_build_barrier=lambda pos: calls.append(pos) or True,
        build_barrier=lambda pos: calls.append(("build", pos)),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is False
    assert calls == []


def test_core_port_guard_allows_second_barrier_when_first_is_alive():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(10, 13), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10), (10, 12)}
    bot.grid = {
        (12, 10): {
            "env": Environment.EMPTY,
            "building": EntityType.BARRIER,
            "building_team": 1,
        },
        (10, 12): {
            "env": Environment.EMPTY,
            "building": None,
            "entity": None,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.last_core_port_barrier_round = -9999
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    barriers = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 11),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
        can_build_barrier=lambda pos: pos == Position(10, 12),
        build_barrier=lambda pos: barriers.append(pos),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is True
    assert barriers == [Position(10, 12)]
    assert bot.last_core_port_barrier_round == 40


def test_core_port_guard_caps_at_two_visible_barriers():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10), (10, 12)}
    bot.grid = {
        (12, 10): {
            "env": Environment.EMPTY,
            "building": EntityType.BARRIER,
            "building_team": 1,
        },
        (10, 12): {
            "env": Environment.EMPTY,
            "building": EntityType.BARRIER,
            "building_team": 1,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.last_core_port_barrier_round = -9999
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
        can_build_barrier=lambda pos: calls.append(pos) or True,
        build_barrier=lambda pos: calls.append(("build", pos)),
    )

    assert defense.core_port_guard_if_needed(bot, controller) is False
    assert calls == []


def test_core_port_guard_does_not_barrier_own_direct_core_lane():
    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)}
    bot.grid = {
        (12, 10): {
            "env": Environment.EMPTY,
            "building": None,
            "entity": None,
        },
    }
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = Position(12, 10)
    bot.core_lane_core_tile_pos = Position(11, 10)
    calls = []

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
    )

    assert defense.core_port_guard_if_needed(bot, controller) is False
    assert calls == []


def test_core_port_guard_uses_bounded_core_slots_not_visible_scan():
    class CountingGrid(dict):
        def __init__(self):
            super().__init__()
            self.get_calls = 0

        def get(self, *args, **kwargs):
            self.get_calls += 1
            return super().get(*args, **kwargs)

    grid = CountingGrid()
    grid[(12, 10)] = {
        "building": EntityType.BARRIER,
        "building_team": 1,
    }
    grid[(10, 12)] = {
        "building": EntityType.BARRIER,
        "building_team": 1,
    }
    for i in range(500):
        grid[(1000 + i, 1000 + i)] = {
            "env": Environment.EMPTY,
            "building": EntityType.ROAD,
            "building_team": 2,
        }

    bot = BuilderBot()
    bot.is_assault_role = False
    bot.builder_mode = BuilderMode.EXPLORING
    bot.core_pos = Position(10, 10)
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(13, 10), EntityType.BUILDER_BOT)
    ]
    bot.visible_positions = {(12, 10)} | {
        (1000 + i, 1000 + i) for i in range(500)
    }
    bot.grid = grid
    bot.titanium_locations = set()
    bot.axionite_locations = set()
    bot.known_friendly_conveyors = set()
    bot.connected_friendly_conveyors = {}
    bot.claimed_pipeline_positions = set()
    bot.tiled_back_positions = set()
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.last_core_port_barrier_round = -9999
    map_calls = {"width": 0, "height": 0}

    controller = SimpleNamespace(
        get_position=lambda: Position(11, 10),
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_map_width=lambda: map_calls.__setitem__("width", map_calls["width"] + 1) or 30,
        get_map_height=lambda: map_calls.__setitem__("height", map_calls["height"] + 1) or 30,
        can_fire=lambda *_args: False,
        can_heal=lambda *_args: False,
    )

    assert defense.core_port_guard_if_needed(bot, controller) is False
    assert grid.get_calls <= 16
    assert map_calls == {"width": 1, "height": 1}


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


def _hijack_open_port_bot(*, current_round=50, current_pos=Position(8, 10)):
    bot = BuilderBot()
    bot.builder_mode = BuilderMode.HIJACKING
    bot.core_pos = Position(2, 2)
    bot.visible_positions = {
        (8, 8),
        (8, 9),
        (current_pos.x, current_pos.y),
    }
    bot.grid = {
        (8, 8): {
            "last_seen": current_round,
            "env": Environment.ORE_TITANIUM,
            "building": EntityType.HARVESTER,
            "building_team": 2,
            "entity": None,
        },
        (8, 9): {
            "last_seen": current_round,
            "env": Environment.EMPTY,
            "building": None,
            "building_team": None,
            "entity": None,
        },
        (current_pos.x, current_pos.y): {
            "last_seen": current_round,
            "env": Environment.EMPTY,
            "building": None,
            "building_team": None,
            "entity": EntityType.BUILDER_BOT,
            "entity_team": 1,
        },
    }
    bot.connected_friendly_conveyors = {(4, 4): 1}
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(8, 8), EntityType.HARVESTER)
    ]
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    return bot


def _hijack_open_port_controller(
    *,
    current_round=50,
    current_pos=Position(8, 10),
    can_build=None,
    built=None,
):
    built = built if built is not None else []
    can_build = can_build or (lambda _pos, _direction: True)
    return SimpleNamespace(
        get_position=lambda: current_pos,
        get_current_round=lambda: current_round,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_global_resources=lambda: (100, 0),
        can_build_sentinel=can_build,
        build_sentinel=lambda pos, direction: built.append((pos, direction)),
    )


def test_hijack_builds_fed_sentinel_on_open_harvester_port():
    built = []
    bot = _hijack_open_port_bot()
    controller = _hijack_open_port_controller(
        built=built,
        can_build=lambda pos, direction: pos == Position(8, 9)
        and direction == Direction.SOUTH,
    )

    mode_hijacking.execute(bot, controller)

    assert built == [(Position(8, 9), Direction.SOUTH)]
    assert bot.hijack_sentinel_pos == Position(8, 9)
    assert bot.hijack_sentinel_harvester_pos == Position(8, 8)
    assert bot.hijack_sentinel_round == 50
    assert bot.builder_mode == BuilderMode.HIJACKING


def test_hijack_sentinel_direction_prioritizes_visible_enemy_builder():
    built = []
    bot = _hijack_open_port_bot()
    bot.visible_enemy_targets = [
        assault.VisibleEnemy(Position(8, 8), EntityType.HARVESTER),
        assault.VisibleEnemy(Position(7, 9), EntityType.BUILDER_BOT),
    ]
    controller = _hijack_open_port_controller(built=built)

    mode_hijacking.execute(bot, controller)

    assert built == [(Position(8, 9), Direction.WEST)]


def test_hijack_moves_to_sentinel_stance_before_entering_open_port(monkeypatch):
    current_pos = Position(8, 11)
    bot = _hijack_open_port_bot(current_pos=current_pos)
    bot.visible_positions.add((8, 10))
    bot.grid[(8, 10)] = {
        "last_seen": 50,
        "env": Environment.EMPTY,
        "building": None,
        "building_team": None,
        "entity": None,
    }
    moved = []
    monkeypatch.setattr(
        navigation,
        "move_towards",
        lambda _bot, _ct, target: moved.append(target),
    )
    controller = _hijack_open_port_controller(current_pos=current_pos)

    mode_hijacking.execute(bot, controller)

    assert moved == [Position(8, 10)]


def test_hijack_without_sentinel_titanium_does_not_stage_for_open_port(monkeypatch):
    current_pos = Position(8, 11)
    bot = _hijack_open_port_bot(current_pos=current_pos)
    bot.visible_positions.add((8, 10))
    bot.grid[(8, 10)] = {
        "last_seen": 50,
        "env": Environment.EMPTY,
        "building": None,
        "building_team": None,
        "entity": None,
    }
    moved = []
    monkeypatch.setattr(
        navigation,
        "move_towards",
        lambda _bot, _ct, target: moved.append(target),
    )
    controller = _hijack_open_port_controller(current_pos=current_pos)
    controller.get_global_resources = lambda: (10, 0)

    mode_hijacking.execute(bot, controller)

    assert moved == [Position(8, 9)]


def test_hijack_does_not_build_second_recent_sentinel_for_same_harvester(monkeypatch):
    built = []
    moved = []
    bot = _hijack_open_port_bot()
    bot.hijack_sentinel_harvester_pos = Position(8, 8)
    bot.hijack_sentinel_pos = Position(8, 9)
    bot.hijack_sentinel_round = 49
    monkeypatch.setattr(
        navigation,
        "move_towards",
        lambda _bot, _ct, target: moved.append(target),
    )
    controller = _hijack_open_port_controller(built=built)

    mode_hijacking.execute(bot, controller)

    assert built == []
    assert moved == [Position(8, 9)]


def test_existing_enemy_harvester_is_blacklisted_not_retiled():
    bot = BuilderBot()
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.ore_target_blacklist = {}
    bot.ore_target_state = {"ore": Position(3, 21), "access": Position(4, 21), "stuck_turns": 2}
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    enemy_harvester_id = 77
    controller = SimpleNamespace(
        get_tile_building_id=lambda _pos: enemy_harvester_id,
        get_entity_type=lambda _entity_id: EntityType.HARVESTER,
        get_team=lambda entity_id=None: "ALLY" if entity_id is None else "ENEMY",
        get_current_round=lambda: 40,
    )

    assert mode_finding_ore._handle_existing_harvester(  # noqa: SLF001
        bot,
        controller,
        Position(3, 21),
    ) is True
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.ore_target_blacklist[(3, 21)] == 40 + mode_finding_ore.ORE_TARGET_BLACKLIST_TTL
    assert bot.ore_target_state == {"ore": None, "access": None, "stuck_turns": 0}


def test_previously_connected_disconnected_friendly_harvester_is_retiled():
    bot = SimpleNamespace(
        known_harvesters={
            (10, 10): {
                "team": 1,
                "adjacent_conveyors": 0,
                "prev_adjacent_conveyors": 1,
            }
        },
        claimed_harvesters=set(),
        shared_connected_harvester_positions=set(),
        ore_target_blacklist={},
        visible_friendly_builders=[],
        grid={},
    )
    controller = SimpleNamespace(
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 10),
        get_current_round=lambda: 107,
        get_id=lambda: 99,
    )

    assert mode_finding_ore._find_disconnected_harvester_to_retile(  # noqa: SLF001
        bot,
        controller,
    ) == (10, 10)


def test_fresh_disconnected_friendly_harvester_without_marker_is_not_retiled():
    bot = SimpleNamespace(
        known_harvesters={
            (10, 10): {
                "team": 1,
                "adjacent_conveyors": 0,
            }
        },
        claimed_harvesters=set(),
        shared_connected_harvester_positions=set(),
        ore_target_blacklist={},
        visible_friendly_builders=[],
        grid={},
    )
    controller = SimpleNamespace(
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 10),
        get_current_round=lambda: 107,
        get_id=lambda: 99,
    )

    assert mode_finding_ore._find_disconnected_harvester_to_retile(  # noqa: SLF001
        bot,
        controller,
    ) is None


def test_connected_harvester_marker_allows_repair_before_stale_delay():
    bot = SimpleNamespace(
        known_harvesters={
            (10, 10): {
                "team": 1,
                "adjacent_conveyors": 0,
            }
        },
        claimed_harvesters=set(),
        shared_connected_harvester_positions={(10, 10)},
        ore_target_blacklist={},
        visible_friendly_builders=[],
        grid={},
    )
    controller = SimpleNamespace(
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 10),
        get_current_round=lambda: 107,
        get_id=lambda: 99,
    )

    assert mode_finding_ore._find_disconnected_harvester_to_retile(  # noqa: SLF001
        bot,
        controller,
    ) == (10, 10)


def test_disconnected_harvester_repair_skips_visible_servicing_builder():
    bot = SimpleNamespace(
        known_harvesters={
            (10, 10): {
                "team": 1,
                "adjacent_conveyors": 0,
                "prev_adjacent_conveyors": 1,
            }
        },
        claimed_harvesters=set(),
        shared_connected_harvester_positions=set(),
        ore_target_blacklist={},
        visible_friendly_builders=[(88, Position(11, 10))],
        grid={},
    )
    controller = SimpleNamespace(
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 10),
        get_current_round=lambda: 107,
        get_id=lambda: 99,
    )

    assert mode_finding_ore._find_disconnected_harvester_to_retile(  # noqa: SLF001
        bot,
        controller,
    ) is None


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


def test_defender_heals_adjacent_damaged_building():
    """Defender within leash radius should heal a damaged adjacent building."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)
    my_team = "A"
    heal_pos = Position(11, 10)  # adjacent, within leash
    bot.grid[(heal_pos.x, heal_pos.y)] = {
        "building": EntityType.CONVEYOR,
        "building_team": my_team,
        "building_hp": 10,
        "building_max_hp": 20,
    }
    bot.visible_positions = {(heal_pos.x, heal_pos.y)}

    healed = []
    controller = SimpleNamespace(
        get_position=lambda *_a: Position(12, 10),
        get_team=lambda *_a: my_team,
        get_current_round=lambda: 10,
        can_heal=lambda pos: pos == heal_pos,
        heal=lambda pos: healed.append(pos),
    )

    result = bot._maybe_defender_hold_or_leash(controller)
    assert result is True
    assert healed == [heal_pos]
    assert bot.healing_this_turn is True


def test_defender_finds_distant_damage_target():
    """Defender within leash radius should find non-adjacent damaged buildings."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)
    my_team = "A"
    damage_pos = Position(12, 10)  # within leash, not adjacent
    bot.grid[(damage_pos.x, damage_pos.y)] = {
        "building": EntityType.CONVEYOR,
        "building_team": my_team,
        "building_hp": 5,
        "building_max_hp": 20,
    }
    bot.visible_positions = {(damage_pos.x, damage_pos.y)}

    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: my_team,
    )

    target = bot._defender_nearest_damaged_building(controller, Position(10, 10))
    assert target == damage_pos


def test_defender_ignores_damage_outside_leash():
    """Defender should not heal buildings outside leash radius."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)
    my_team = "A"
    far_pos = Position(20, 10)  # outside 5-tile leash
    bot.grid[(far_pos.x, far_pos.y)] = {
        "building": EntityType.CONVEYOR,
        "building_team": my_team,
        "building_hp": 5,
        "building_max_hp": 20,
    }
    bot.visible_positions = {(far_pos.x, far_pos.y)}

    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: my_team,
        get_current_round=lambda: 10,
    )

    result = bot._maybe_defender_hold_or_leash(controller)
    assert result is False  # no action taken


def test_defender_no_heal_when_no_damage():
    """Defender with no damaged buildings should fall through."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)
    my_team = "A"
    healthy_pos = Position(11, 10)
    bot.grid[(healthy_pos.x, healthy_pos.y)] = {
        "building": EntityType.CONVEYOR,
        "building_team": my_team,
        "building_hp": 20,
        "building_max_hp": 20,
    }
    bot.visible_positions = {(healthy_pos.x, healthy_pos.y)}

    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: my_team,
        get_current_round=lambda: 10,
    )

    result = bot._maybe_defender_hold_or_leash(controller)
    assert result is False


def test_defender_demoted_after_no_harvester():
    """Defender should lose its role after DEFENDER_ROLE_DEMOTION_ROUND if
    it never placed a harvester."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)

    # Before demotion round: stays defender
    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: "A",
        get_current_round=lambda: builder_bot.DEFENDER_ROLE_DEMOTION_ROUND - 1,
    )
    assert bot._maybe_defender_hold_or_leash(controller) is False
    assert bot.is_defender_role is True

    # At demotion round with no harvester: demoted
    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: "A",
        get_current_round=lambda: builder_bot.DEFENDER_ROLE_DEMOTION_ROUND,
    )
    assert bot._maybe_defender_hold_or_leash(controller) is False
    assert bot.is_defender_role is False


def test_defender_keeps_role_until_deadline_with_harvester():
    """Defender should keep its role before the deadline even if it placed a harvester."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)
    bot.last_harvester_pos = Position(12, 12)  # has placed a harvester

    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: "A",
        get_current_round=lambda: builder_bot.DEFENDER_ROLE_DEMOTION_ROUND - 1,
    )
    assert bot._maybe_defender_hold_or_leash(controller) is False
    assert bot.is_defender_role is True  # NOT demoted before deadline


def test_defender_demotes_at_deadline_even_with_harvester():
    """After the core-defense window, the defender should rejoin economy/pressure."""
    bot = BuilderBot()
    bot.is_defender_role = True
    bot.core_pos = Position(10, 10)
    bot.last_harvester_pos = Position(12, 12)

    controller = SimpleNamespace(
        get_position=lambda *_a: Position(10, 10),
        get_team=lambda *_a: "A",
        get_current_round=lambda: builder_bot.DEFENDER_ROLE_DEMOTION_ROUND,
    )
    assert bot._maybe_defender_hold_or_leash(controller) is False
    assert bot.is_defender_role is False


def test_delta_perception_skips_persisted_tiles():
    """Full scan with delta perception should skip SDK calls for persisted tiles."""
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    # Simulate previous visible set: tiles around (10, 10)
    prev = set()
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            if dx*dx + dy*dy <= 20:  # vision radius
                prev.add((10+dx, 10+dy))
    bot.previous_visible_positions = prev

    # The delta machinery should produce entered + safety_ring as fresh tiles,
    # and persisted tiles should NOT call SDK.
    assert perception.FAST_SCAN_RADIUS_SQ == 9
    assert len(prev) > 0  # sanity check


def test_delta_perception_first_turn_scans_all():
    """On the first turn (no previous visible), all tiles should be fresh."""
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    assert len(bot.previous_visible_positions) == 0


def test_tiling_back_fast_scan_uses_reduced_radius():
    """TILING_BACK fast scans should use the tighter TILING_FAST_SCAN_RADIUS_SQ
    to reduce SDK call count while preserving immediate obstacle detection."""
    assert perception.TILING_FAST_SCAN_RADIUS_SQ < perception.FAST_SCAN_RADIUS_SQ
    assert perception.TILING_FAST_SCAN_RADIUS_SQ == 2


def test_non_tiling_fast_scan_uses_normal_radius():
    """FINDING_ORE and other modes should still use the full FAST_SCAN_RADIUS_SQ."""
    assert perception.FAST_SCAN_RADIUS_SQ == 9


def test_scan_micro_detects_enemy_units():
    """scan_micro should populate visible_enemy_targets from get_nearby_units."""
    bot = BuilderBot()
    my_pos = Position(5, 5)
    enemy_pos = Position(7, 7)
    enemy_core_pos = Position(10, 10)
    friendly_pos = Position(4, 4)

    my_team = "A"
    enemy_team = "B"
    unit_data = {
        100: (enemy_pos, EntityType.BUILDER_BOT, enemy_team),
        200: (friendly_pos, EntityType.BUILDER_BOT, my_team),
        300: (enemy_core_pos, EntityType.CORE, enemy_team),
    }

    controller = SimpleNamespace(
        get_team=lambda *args: my_team if not args else unit_data[args[0]][2],
        get_position=lambda *args: my_pos if not args else unit_data[args[0]][0],
        get_id=lambda: 1,
        get_current_round=lambda: 20,
        get_entity_type=lambda uid: unit_data[uid][1],
        get_nearby_units=lambda: list(unit_data.keys()),
    )

    perception.scan_micro(bot, controller)

    # Should detect enemy builder and enemy core
    assert len(bot.visible_enemy_targets) == 2
    enemy_types = {e.entity_type for e in bot.visible_enemy_targets}
    assert EntityType.BUILDER_BOT in enemy_types
    assert EntityType.CORE in enemy_types

    # Should track enemy core position
    assert bot.enemy_core_anchor == enemy_core_pos
    assert bot.enemy_core_exact is True

    # Should track friendly builder
    assert (friendly_pos.x, friendly_pos.y) in bot.bot_locations
    assert (my_pos.x, my_pos.y) in bot.bot_locations
    assert len(bot.visible_friendly_builders) == 2  # self + friendly


def test_scan_micro_skips_position_for_friendly_non_builder():
    bot = BuilderBot()
    my_pos = Position(5, 5)
    friendly_core_pos = Position(6, 5)
    enemy_pos = Position(8, 8)
    unit_data = {
        100: (friendly_core_pos, EntityType.CORE, "A"),
        200: (enemy_pos, EntityType.BUILDER_BOT, "B"),
    }
    position_calls = []

    def get_position(*args):
        if not args:
            return my_pos
        unit_id = args[0]
        position_calls.append(unit_id)
        if unit_id == 100:
            raise AssertionError("friendly non-builder position should not be read")
        return unit_data[unit_id][0]

    controller = SimpleNamespace(
        get_team=lambda *args: "A" if not args else unit_data[args[0]][2],
        get_position=get_position,
        get_id=lambda: 1,
        get_current_round=lambda: 20,
        get_entity_type=lambda uid: unit_data[uid][1],
        get_nearby_units=lambda: list(unit_data.keys()),
    )

    perception.scan_micro(bot, controller)

    assert position_calls == [200]
    assert len(bot.visible_enemy_targets) == 1
    assert bot.visible_enemy_targets[0].position == enemy_pos
    assert (friendly_core_pos.x, friendly_core_pos.y) not in bot.bot_locations


def test_scan_micro_preserves_grid_data():
    """scan_micro should preserve static grid data, ore sets, and topology."""
    bot = BuilderBot()
    bot.titanium_locations.add(Position(3, 3))
    bot.grid[(3, 3)] = {"env": "ORE_TITANIUM", "last_seen": 10}
    bot.grid[(5, 5)] = {"env": "EMPTY", "building": None, "last_seen": 10}
    original_grid = dict(bot.grid)

    controller = SimpleNamespace(
        get_team=lambda *args: "A",
        get_position=lambda *args: Position(5, 5),
        get_id=lambda: 1,
        get_current_round=lambda: 20,
        get_entity_type=lambda uid: EntityType.BUILDER_BOT,
        get_nearby_units=lambda: [],
    )

    perception.scan_micro(bot, controller)

    # Grid should be unchanged
    assert bot.grid == original_grid
    # Ore set should be unchanged
    assert Position(3, 3) in bot.titanium_locations


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
    ct = SimpleNamespace(
        get_team=lambda *_a: 1,
        get_tile_building_id=lambda pos: 42,
        get_entity_type=lambda bid: EntityType.SPLITTER,
    )

    assert mode_tiling_back._check_connect_to_conveyor(
        bot, ct, Position(5, 3), Position(5, 3), TargetKind.CONVEYOR
    )


def test_tiling_back_adjacent_merge_verifies_live_connected_target():
    bot = SimpleNamespace(
        pending_build=None,
        connected_friendly_conveyors={(5, 3): 2},
    )
    ids = {(5, 4): 10, (5, 3): 20}
    types = {10: EntityType.CONVEYOR, 20: EntityType.BRIDGE}
    directions = {10: Direction.NORTH}
    ct = SimpleNamespace(
        get_team=lambda *_a: 1,
        get_tile_building_id=lambda pos: ids.get((pos.x, pos.y)),
        get_entity_type=lambda bid: types[bid],
        get_direction=lambda bid: directions[bid],
    )

    assert mode_tiling_back._check_connect_to_conveyor(
        bot, ct, Position(5, 4), Position(5, 3), TargetKind.CONVEYOR
    )


def test_tiling_back_adjacent_merge_rejects_stale_missing_target():
    bot = SimpleNamespace(
        pending_build=None,
        connected_friendly_conveyors={(5, 3): 2},
    )
    ids = {(5, 4): 10}
    ct = SimpleNamespace(
        get_team=lambda *_a: 1,
        get_tile_building_id=lambda pos: ids.get((pos.x, pos.y)),
        get_entity_type=lambda _bid: EntityType.CONVEYOR,
        get_direction=lambda _bid: Direction.NORTH,
    )

    assert not mode_tiling_back._check_connect_to_conveyor(
        bot, ct, Position(5, 4), Position(5, 3), TargetKind.CONVEYOR
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


def test_orphan_adjacent_harvester_enters_tiling_back_for_repair():
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
    bot.connected_friendly_conveyors = {}
    built = []
    controller = SimpleNamespace(
        get_current_round=lambda: 80,
        get_team=lambda *_args: 1,
        get_position=lambda: Position(5, 4),
        build_harvester=lambda pos: built.append(pos),
        get_stored_resource_id=lambda _entity_id: None,
        get_stored_resource=lambda _entity_id: None,
    )

    switched = mode_finding_ore._build_harvester_and_switch_mode(  # noqa: SLF001
        bot,
        controller,
        Position(5, 5),
    )

    assert switched is True
    assert built == [Position(5, 5)]
    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.tiling_force_core_return is False
    assert (5, 5) not in bot.claimed_harvesters


def test_existing_harvester_with_only_orphan_adjacent_conveyor_retiles():
    bot = BuilderBot()
    bot.core_pos = Position(10, 10)
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.grid = {
        (5, 6): {
            "building_id": 61,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
        },
    }
    bot.connected_friendly_conveyors = {}
    bot.claimed_harvesters = set()
    controller = SimpleNamespace(
        get_current_round=lambda: 80,
        get_team=lambda *_args: 1,
        get_tile_building_id=lambda pos: 99 if pos == Position(5, 5) else None,
        get_entity_type=lambda _entity_id: EntityType.HARVESTER,
    )

    handled = mode_finding_ore._handle_existing_harvester(  # noqa: SLF001
        bot,
        controller,
        Position(5, 5),
    )

    assert handled is True
    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert (5, 5) not in bot.claimed_harvesters


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
    assert mode_tiling_back._is_core_approach_slot(  # noqa: SLF001
        bot,
        bot.core_lane_slot_pos,
    )
    assert bot.core_lane_core_tile_pos == target

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


def test_ore_target_build_failures_switch_to_exploring():
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.ore_target_blacklist = {}
    bot.ore_target_state = {"ore": None, "access": None, "stuck_turns": 0}
    bot.pathfinding_state = {
        "path": [],
        "planner_state": None,
        "last_replan_signature": None,
        "temporary_obstacles": {},
    }
    controller = SimpleNamespace(get_current_round=lambda: 50)
    ore_pos = Position(7, 9)
    access_pos = Position(6, 9)

    for _ in range(mode_finding_ore.ORE_TARGET_BUILD_RETRY_TURNS - 1):
        assert mode_finding_ore._note_ore_target_build_failure(  # noqa: SLF001
            bot,
            controller,
            ore_pos,
            access_pos,
        ) is False

    assert mode_finding_ore._note_ore_target_build_failure(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
    ) is True
    assert bot.builder_mode == BuilderMode.EXPLORING
    assert bot.ore_target_blacklist == {(7, 9): 50 + mode_finding_ore.ORE_TARGET_BLACKLIST_TTLS[0]}
    assert bot.ore_target_state == {"ore": None, "access": None, "stuck_turns": 0}
    assert (7, 9) not in bot.ore_target_build_fail_streaks


def test_ore_target_build_failures_reset_by_progress():
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    controller = SimpleNamespace(get_current_round=lambda: 50)
    ore_pos = Position(7, 9)
    access_pos = Position(6, 9)

    mode_finding_ore._note_ore_target_build_failure(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
    )
    assert bot.ore_target_build_fail_streaks[((7, 9), (6, 9))] == 1
    mode_finding_ore._note_ore_target_progress(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
        moved=True,
    )
    assert bot.ore_target_build_fail_streaks == {}
    assert mode_finding_ore._note_ore_target_build_failure(  # noqa: SLF001
        bot,
        controller,
        ore_pos,
        access_pos,
    ) is False


def test_execute_abandons_unbuildable_ore_after_retries(monkeypatch):
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.claimed_harvesters = set()
    bot.bot_locations = set()
    bot.axionite_locations = set()
    bot.titanium_locations = set()
    bot.shared_ore_positions = set()
    bot.ore_target_blacklist = {}
    bot.ore_target_state = {"ore": None, "access": None, "stuck_turns": 0}
    bot.grid = {}
    bot.connected_friendly_conveyors = {}
    bot.pathfinding_state = {
        "path": [],
        "planner_state": None,
        "last_replan_signature": None,
        "temporary_obstacles": {},
        "known_obstacles": set(),
    }
    bot.builder_mode = BuilderMode.FINDING_ORE
    bot.connected_friendly_conveyors = {}
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_position=lambda: Position(6, 9),
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_harvester=lambda _pos: False,
        get_tile_building_id=lambda _pos: None,
        get_harvester_cost=lambda: 1,
        get_global_resources=lambda: (1, 0),
        get_team=lambda: 1,
    )

    monkeypatch.setattr(
        mode_finding_ore,
        "_find_best_ore_target",
        lambda _bot, _ct: (Position(7, 9), Position(6, 9), 1),
    )
    for _ in range(mode_finding_ore.ORE_TARGET_BUILD_RETRY_TURNS - 1):
        mode_finding_ore.execute(bot, controller)
        assert bot.builder_mode == BuilderMode.FINDING_ORE

    mode_finding_ore.execute(bot, controller)
    assert bot.builder_mode == BuilderMode.EXPLORING
    assert (7, 9) in bot.ore_target_blacklist


def test_execute_waits_for_harvester_titanium_without_blacklisting(monkeypatch):
    bot = BuilderBot()
    bot.logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    bot.claimed_harvesters = set()
    bot.bot_locations = set()
    bot.axionite_locations = set()
    bot.titanium_locations = set()
    bot.shared_ore_positions = set()
    bot.ore_target_blacklist = {}
    bot.ore_target_state = {"ore": None, "access": None, "stuck_turns": 0}
    bot.ore_target_build_fail_streaks = {((7, 9), (6, 9)): 2}
    bot.grid = {}
    bot.connected_friendly_conveyors = {}
    bot.pathfinding_state = {
        "path": [],
        "planner_state": None,
        "last_replan_signature": None,
        "temporary_obstacles": {},
        "known_obstacles": set(),
    }
    bot.builder_mode = BuilderMode.FINDING_ORE
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_position=lambda: Position(6, 9),
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_harvester=lambda _pos: False,
        get_tile_building_id=lambda _pos: None,
        get_harvester_cost=lambda: (20, 0),
        get_global_resources=lambda: (5, 0),
        get_team=lambda: 1,
    )

    monkeypatch.setattr(
        mode_finding_ore,
        "_find_best_ore_target",
        lambda _bot, _ct: (Position(7, 9), Position(6, 9), 1),
    )

    for _ in range(mode_finding_ore.ORE_TARGET_BUILD_RETRY_TURNS + 1):
        mode_finding_ore.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.ore_target_blacklist == {}
    assert bot.ore_target_build_fail_streaks == {}


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


def test_try_pathfinding_move_routes_around_enemy_builder_blocker(monkeypatch):
    """A visible enemy builder blocking the actual next edge becomes a
    short-lived obstacle, independent of broad enemy threat visibility."""
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
        blocker_tile={"entity": EntityType.BUILDER_BOT, "entity_team": 2, "id": 99},
    )

    moved, _ = navigation.try_pathfinding_move(bot, controller, Position(12, 10))

    assert moved is False
    assert bot.pathfinding_state["temporary_obstacles"][(12, 10)] == 23


def test_try_pathfinding_move_does_not_route_around_allowed_enemy_builder_target(monkeypatch):
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
        blocker_tile={
            "entity": EntityType.BUILDER_BOT,
            "entity_team": 2,
            "id": 99,
        },
    )

    moved, _ = navigation.try_pathfinding_move(
        bot,
        controller,
        Position(12, 10),
        allow_enemy_builder_at_target=True,
    )

    assert moved is False
    assert (12, 10) not in bot.pathfinding_state["temporary_obstacles"]


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


def _run_resumable_astar_to_completion(
    bot,
    controller,
    start,
    target,
    *,
    known_obstacles,
    cardinal_only=False,
    allow_bridges=None,
):
    planner = None
    latest_path = []
    for _ in range(8):
        path, exact, planner = navigation._resume_anytime_astar(  # noqa: SLF001
            bot,
            controller,
            start,
            target,
            known_obstacles=known_obstacles,
            cardinal_only=cardinal_only,
            planner_state=planner,
            allow_bridges=allow_bridges,
        )
        if path:
            latest_path = path
        if exact or planner is None:
            return path
    raise AssertionError("resumable A* did not finish within test slices")


def test_resumable_astar_matches_sync_astar_on_clear_cardinal_path(monkeypatch):
    monkeypatch.setattr(navigation, "ANYTIME_ASTAR_MIN_ITERATIONS", 512)
    monkeypatch.setattr(navigation, "_get_astar_limits", lambda _bot: (512, 1_000_000))
    controller = SimpleNamespace(
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        get_team=lambda: 1,
        draw_indicator_dot=lambda *_args, **_kwargs: None,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.FINDING_ORE,
        pending_bridge_plan=None,
        grid={},
        connected_friendly_conveyors={},
        turn_decision_deadline_ns=0,
        logger=SimpleNamespace(print=lambda *_args, **_kwargs: None),
        stats={},
    )

    sync_path = navigation.calculate_astar_path(
        bot,
        controller,
        Position(0, 0),
        Position(4, 0),
        known_obstacles=set(),
        cardinal_only=True,
        allow_bridges=False,
    )
    resumable_path = _run_resumable_astar_to_completion(
        bot,
        controller,
        Position(0, 0),
        Position(4, 0),
        known_obstacles=set(),
        cardinal_only=True,
        allow_bridges=False,
    )

    assert resumable_path == sync_path


def test_tiling_back_straight_cardinal_path_skips_astar(monkeypatch):
    def fail_anytime(*_args, **_kwargs):
        raise AssertionError("straight tiling path should not need resumable A*")

    def fail_full_astar(*_args, **_kwargs):
        raise AssertionError("straight tiling path should not need full A*")

    monkeypatch.setattr(navigation, "_resume_anytime_astar", fail_anytime)
    monkeypatch.setattr(navigation, "calculate_astar_path", fail_full_astar)

    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        grid={},
        connected_friendly_conveyors={},
        pending_bridge_plan=None,
        stats={},
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 10,
        get_team=lambda: 1,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
    )

    move_action, new_state = navigation.compute_pathfinding_step(
        bot,
        controller,
        Position(0, 0),
        Position(0, 4),
        {
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "current_target": (0, 4),
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
            "planner_state": None,
        },
        cardinal_only=True,
    )

    assert move_action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)
    assert new_state["path"] == [
        (navigation.ActionType.CONVEYOR, Direction.SOUTH),
        (navigation.ActionType.CONVEYOR, Direction.SOUTH),
        (navigation.ActionType.CONVEYOR, Direction.SOUTH),
        (navigation.ActionType.CONVEYOR, Direction.SOUTH),
    ]
    assert bot.stats["straight_tiling_paths"] == 1


def test_straight_tiling_path_rejects_wrong_way_friendly_transport():
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        grid={
            (0, 1): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            }
        },
        connected_friendly_conveyors={},
        stats={},
    )
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
    )

    path = navigation._calculate_straight_tiling_path_if_clear(  # noqa: SLF001
        bot,
        controller,
        Position(0, 0),
        Position(0, 3),
        known_obstacles=set(),
    )

    assert path == []


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
    assert max(abs(bot.return_target_pos.x - 10), abs(bot.return_target_pos.y - 10)) <= 1
    assert mode_tiling_back._is_core_approach_slot(bot, bot.core_lane_slot_pos)  # noqa: SLF001
    assert bot.return_target_pos == bot.core_lane_core_tile_pos


def test_return_target_selects_closer_conveyor_without_hysteresis_gate(monkeypatch):
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        connected_friendly_conveyors={(8, 0): 0},
        tiled_back_positions=set(),
        tiling_force_core_return=False,
        tiling_prefer_core_return=False,
        tiling_core_approach_full=False,
        core_return_target_pos=None,
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        return_target_pos=Position(10, 0),
        return_target_dist_manhatten=10,
        return_target_kind=TargetKind.CORE,
        last_return_target_refresh_round=-1,
        last_connected_refresh_round=0,
    )
    controller = SimpleNamespace(get_current_round=lambda: 20)

    monkeypatch.setattr(
        mode_tiling_back,
        "_select_core_return_target",
        lambda *_args: Position(10, 0),
    )
    monkeypatch.setattr(
        mode_tiling_back,
        "_core_approach_ring_visibly_full",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        mode_tiling_back,
        "_nearest_connected_conveyor",
        lambda *_args: (Position(8, 0), 8, 8),
    )

    mode_tiling_back._update_return_target_while_tiling(  # noqa: SLF001
        bot,
        controller,
        Position(0, 0),
    )

    assert bot.return_target_kind == TargetKind.CONVEYOR
    assert bot.return_target_pos == Position(8, 0)
    assert bot.nearest_conveyor_pos == Position(8, 0)


def test_return_target_does_not_pin_existing_conveyor(monkeypatch):
    bot = SimpleNamespace(
        core_pos=Position(10, 10),
        connected_friendly_conveyors={(13, 0): 0},
        tiled_back_positions=set(),
        tiling_force_core_return=False,
        tiling_prefer_core_return=False,
        tiling_core_approach_full=False,
        core_return_target_pos=None,
        nearest_conveyor_pos=Position(13, 0),
        nearest_conveyor_dist_manhatten=13,
        return_target_pos=Position(13, 0),
        return_target_dist_manhatten=13,
        return_target_kind=TargetKind.CONVEYOR,
        last_return_target_refresh_round=-1,
        last_connected_refresh_round=0,
    )
    controller = SimpleNamespace(get_current_round=lambda: 20)

    monkeypatch.setattr(
        mode_tiling_back,
        "_select_core_return_target",
        lambda *_args: Position(10, 0),
    )
    monkeypatch.setattr(
        mode_tiling_back,
        "_core_approach_ring_visibly_full",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        mode_tiling_back,
        "_nearest_connected_conveyor",
        lambda *_args: (Position(13, 0), 13, 13),
    )

    mode_tiling_back._update_return_target_while_tiling(  # noqa: SLF001
        bot,
        controller,
        Position(0, 0),
    )

    assert bot.return_target_kind == TargetKind.CORE
    assert bot.return_target_pos == Position(10, 0)


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


def test_nonbridge_replan_defers_full_astar_while_anytime_is_active(monkeypatch):
    planner = {"signature": ("active",), "open_set": [("placeholder",)]}
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
        lambda *_args, **_kwargs: ([], False, planner),
    )

    def fail_full_astar(*_args, **_kwargs):
        raise AssertionError("non-bridge replan should resume instead of full A*")

    monkeypatch.setattr(navigation, "calculate_astar_path", fail_full_astar)

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
            can_move=lambda _d: False,
        ),
        Position(0, 0),
        Position(5, 5),
        {
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "current_target": (5, 5),
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
            "planner_state": None,
        },
        cardinal_only=False,
    )

    assert move_action is None
    assert new_state["planner_state"] is planner


def test_planner_signature_changes_when_obstacle_identity_changes():
    """Obstacle fingerprint uses full content hash so different obstacle
    positions produce different signatures, even with the same count."""
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


def test_compute_pathfinding_step_expires_temp_obstacles_with_one_round_read():
    round_reads = 0

    def get_current_round():
        nonlocal round_reads
        round_reads += 1
        return 10

    move_action, new_state = navigation.compute_pathfinding_step(
        SimpleNamespace(
            builder_mode=BuilderMode.FINDING_ORE,
            grid={},
            connected_friendly_conveyors={},
            pending_bridge_plan=None,
            stats={},
        ),
        SimpleNamespace(
            get_current_round=get_current_round,
            get_team=lambda: 1,
            get_map_width=lambda: 20,
            get_map_height=lambda: 20,
        ),
        Position(0, 0),
        Position(0, 3),
        {
            "known_obstacles": set(),
            "path": [
                (navigation.ActionType.CONVEYOR, Direction.SOUTH),
                (navigation.ActionType.CONVEYOR, Direction.SOUTH),
                (navigation.ActionType.CONVEYOR, Direction.SOUTH),
            ],
            "temporary_obstacles": {
                (7, 7): 10,
                (8, 8): 9,
                (9, 9): 11,
            },
            "current_target": (0, 3),
            "last_obstacle_signature": None,
            "last_replan_signature": None,
            "last_replan_round": -1,
            "planner_state": None,
        },
    )

    assert move_action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)
    assert new_state["temporary_obstacles"] == {(9, 9): 11}
    assert round_reads == 1


def test_compute_pathfinding_step_reuses_state_and_path_on_cache_hit(monkeypatch):
    def fail_replan(*_args, **_kwargs):
        raise AssertionError("cached path should not replan")

    monkeypatch.setattr(navigation, "_resume_anytime_astar", fail_replan)

    path = [(navigation.ActionType.CONVEYOR, Direction.SOUTH)]
    state = {
        "known_obstacles": set(),
        "path": path,
        "temporary_obstacles": {},
        "current_target": (0, 1),
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": {"signature": "planner"},
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
        state,
    )

    assert move_action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)
    assert new_state is state
    assert new_state["path"] is path


def test_compute_pathfinding_step_failed_astar_cooldown_skips_same_signature(monkeypatch):
    astar_calls = 0

    def exhausted_astar(*_args, **_kwargs):
        nonlocal astar_calls
        astar_calls += 1
        return [], False, None

    monkeypatch.setattr(navigation, "_resume_anytime_astar", exhausted_astar)
    monkeypatch.setattr(navigation, "calculate_micro_plan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        navigation,
        "FAILED_ASTAR_COOLDOWN_TURNS",
        3,
    )

    round_now = {"value": 10}
    controller = SimpleNamespace(
        get_current_round=lambda: round_now["value"],
        get_team=lambda: 1,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        can_move=lambda _direction: False,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.FINDING_ORE,
        grid={},
        connected_friendly_conveyors={},
        pending_bridge_plan=None,
        turn_decision_deadline_ns=0,
        stats={},
    )
    state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": (5, 0),
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": None,
    }

    first_action, first_state = navigation.compute_pathfinding_step(
        bot,
        controller,
        Position(0, 0),
        Position(5, 0),
        state,
        cardinal_only=True,
    )
    round_now["value"] = 11
    second_action, second_state = navigation.compute_pathfinding_step(
        bot,
        controller,
        Position(0, 0),
        Position(5, 0),
        state,
        cardinal_only=True,
    )

    assert first_action is None
    assert second_action is None
    assert first_state is state
    assert second_state is state
    assert astar_calls == 1
    assert state["failed_astar_signature"] is not None
    assert state["failed_astar_cooldown_until"] == 13


def test_compute_pathfinding_step_failed_astar_retries_when_signature_changes(monkeypatch):
    astar_calls = 0

    def exhausted_astar(*_args, **_kwargs):
        nonlocal astar_calls
        astar_calls += 1
        return [], False, None

    monkeypatch.setattr(navigation, "_resume_anytime_astar", exhausted_astar)
    monkeypatch.setattr(navigation, "calculate_micro_plan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(navigation, "FAILED_ASTAR_COOLDOWN_TURNS", 3)

    round_now = {"value": 10}
    controller = SimpleNamespace(
        get_current_round=lambda: round_now["value"],
        get_team=lambda: 1,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
        can_move=lambda _direction: False,
    )
    bot = SimpleNamespace(
        builder_mode=BuilderMode.FINDING_ORE,
        grid={},
        connected_friendly_conveyors={},
        pending_bridge_plan=None,
        turn_decision_deadline_ns=0,
        stats={},
    )
    state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": (5, 0),
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": None,
    }

    navigation.compute_pathfinding_step(
        bot,
        controller,
        Position(0, 0),
        Position(5, 0),
        state,
        cardinal_only=True,
    )
    state["known_obstacles"].add((2, 0))
    round_now["value"] = 11
    navigation.compute_pathfinding_step(
        bot,
        controller,
        Position(0, 0),
        Position(5, 0),
        state,
        cardinal_only=True,
    )

    assert astar_calls == 2


def test_compute_pathfinding_step_keeps_resumable_astar_active(monkeypatch):
    planner = {
        "signature": ("same",),
        "open_set": [("placeholder",)],
        "came_from": {},
        "g_costs": {},
        "depths": {},
    }
    current_pos = Position(0, 0)
    target_pos = Position(5, 5)
    target_tuple = (target_pos.x, target_pos.y)
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        grid={},
        connected_friendly_conveyors={},
        pending_bridge_plan=None,
        tiling_force_core_return=False,
        tiling_core_approach_full=False,
        stats={},
    )
    state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": target_tuple,
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": planner,
    }
    monkeypatch.setattr(
        navigation,
        "_resume_anytime_astar",
        lambda *args, **kwargs: ([], False, planner),
    )

    def fail_full_astar(*_args, **_kwargs):
        raise AssertionError("runtime should keep resumable A* active")

    monkeypatch.setattr(navigation, "calculate_astar_path", fail_full_astar)

    move_action, new_state = navigation.compute_pathfinding_step(
        bot,
        SimpleNamespace(
            get_current_round=lambda: 10,
            get_team=lambda: 1,
            get_map_width=lambda: 20,
            get_map_height=lambda: 20,
            can_move=lambda _d: False,
        ),
        current_pos,
        target_pos,
        state,
        cardinal_only=True,
    )

    # Without any legal cardinal move (can_move always False), the
    # bugnav fallback cannot produce a step and the builder must no-op,
    # leaving the resumable planner attached so the next turn resumes
    # from where it left off.
    assert move_action is None
    assert new_state["planner_state"] is planner


def test_compute_pathfinding_step_bugnav_fallback_unfreezes_tiling_back(monkeypatch):
    # When resumable A* returns an empty path AND there is no active
    # planner state, the tiling-back builder used to return None and
    # stay frozen. Replay evidence from `cold` vs `leeroy` showed
    # builder #5 stuck at (13,13) for 1997 turns. The bugnav fallback
    # should emit one safe greedy step toward the target.
    current_pos = Position(0, 0)
    target_pos = Position(5, 5)
    target_tuple = (target_pos.x, target_pos.y)
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        grid={},
        connected_friendly_conveyors={},
        pending_bridge_plan=None,
        tiling_force_core_return=False,
        tiling_core_approach_full=False,
        stats={},
    )
    state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": target_tuple,
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": None,
    }
    monkeypatch.setattr(
        navigation,
        "_resume_anytime_astar",
        lambda *args, **kwargs: ([], False, None),
    )
    monkeypatch.setattr(
        navigation,
        "calculate_micro_plan",
        lambda *args, **kwargs: [],
    )

    move_action, new_state = navigation.compute_pathfinding_step(
        bot,
        SimpleNamespace(
            get_current_round=lambda: 10,
            get_team=lambda: 1,
            get_map_width=lambda: 20,
            get_map_height=lambda: 20,
            can_move=lambda _d: True,
        ),
        current_pos,
        target_pos,
        state,
        cardinal_only=True,
    )

    # Greedy step toward (5, 5) from (0, 0): either EAST or SOUTH
    # (both reduce manhattan by 1 to 9).
    assert move_action is not None
    assert move_action[0] == navigation.ActionType.CONVEYOR
    assert move_action[1] in (Direction.EAST, Direction.SOUTH)


def test_compute_pathfinding_step_uses_resumable_path_instead_of_sync_astar(monkeypatch):
    planner = {
        "signature": ("same",),
        "open_set": [("placeholder",)],
        "came_from": {},
        "g_costs": {},
        "depths": {},
    }
    current_pos = Position(0, 0)
    target_pos = Position(5, 5)
    target_tuple = (target_pos.x, target_pos.y)
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        grid={},
        connected_friendly_conveyors={},
        pending_bridge_plan=None,
        tiling_force_core_return=False,
        tiling_core_approach_full=False,
        stats={},
    )
    state = {
        "known_obstacles": set(),
        "path": [],
        "temporary_obstacles": {},
        "current_target": target_tuple,
        "last_obstacle_signature": None,
        "last_replan_signature": None,
        "last_replan_round": -1,
        "planner_state": planner,
    }
    monkeypatch.setattr(
        navigation,
        "_resume_anytime_astar",
        lambda *args, **kwargs: (
            [(navigation.ActionType.CONVEYOR, Direction.SOUTH)],
            False,
            planner,
        ),
    )

    def fail_full_astar(*_args, **_kwargs):
        raise AssertionError("runtime should not call synchronous A*")

    monkeypatch.setattr(navigation, "calculate_astar_path", fail_full_astar)

    move_action, new_state = navigation.compute_pathfinding_step(
        bot,
        SimpleNamespace(
            get_current_round=lambda: 10,
            get_team=lambda: 1,
            get_map_width=lambda: 20,
            get_map_height=lambda: 20,
        ),
        current_pos,
        target_pos,
        state,
        cardinal_only=True,
    )

    assert move_action == (navigation.ActionType.CONVEYOR, Direction.SOUTH)
    assert new_state["planner_state"] is planner


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


def test_pending_bridge_can_output_to_protected_connected_transport():
    start = Position(5, 5)
    target = Position(8, 5)
    built = []
    bot = SimpleNamespace(
        pending_build=(ActionType.BRIDGE, start, target),
        pathfinding_state={"temporary_obstacles": {}, "path": [], "planner_state": None},
        grid={
            (start.x, start.y): {"building": None, "building_team": None},
            (target.x, target.y): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
            },
        },
        connected_friendly_conveyors={(target.x, target.y): 1},
        claimed_pipeline_positions=set(),
        tiled_back_positions=set(),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_team=lambda *_args: 1,
        get_current_round=lambda: 20,
        get_tile_building_id=lambda pos: None,
        can_build_bridge=lambda pos, target_pos: pos == start and target_pos == target,
        build_bridge=lambda pos, target_pos: built.append((pos, target_pos)),
    )

    assert mode_tiling_back._execute_pending_build(bot, controller) is True

    assert built == [(start, target)]
    assert bot.pending_build is None
    assert (start.x, start.y) in bot.tiled_back_positions
    assert (target.x, target.y) in bot.tiled_back_positions


def test_bridge_transit_partial_exhaustion_builds_bridge_directly(monkeypatch):
    start = Position(5, 5)
    target = Position(8, 5)
    built = []
    planner_calls = []

    monkeypatch.setattr(navigation, "calculate_micro_plan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(navigation, "get_available_astar_time_budget", lambda *_args, **_kwargs: 1_000_000)

    def partial_exhausted(*_args, **_kwargs):
        planner_calls.append(True)
        return [(ActionType.CONVEYOR, Direction.EAST)], False, None

    monkeypatch.setattr(navigation, "_resume_anytime_astar", partial_exhausted)

    bot = SimpleNamespace(
        bridge_transit_path=None,
        pending_bridge_plan=(start, target),
        bridge_transit_planner_state=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "known_obstacles": set(),
            "temporary_obstacles": {},
            "path": [(ActionType.BRIDGE, target)],
            "planner_state": {"signature": "planner"},
        },
        stats={"double_astar_turns": 0},
        tiled_back_positions=set(),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: start,
        get_current_round=lambda: 30,
        get_team=lambda: 1,
        can_build_bridge=lambda pos, target_pos: pos == start and target_pos == target,
        build_bridge=lambda pos, target_pos: built.append((pos, target_pos)),
    )

    mode_tiling_back._navigate_and_build(bot, controller, start, Position(10, 5))

    assert planner_calls
    assert built == [(start, target)]
    assert bot.pending_bridge_plan is None
    assert bot.bridge_transit_path is None
    assert bot.bridge_transit_planner_state is None
    assert bot.pathfinding_state["path"] == []


def test_bridge_transit_partial_active_planner_keeps_pending_plan(monkeypatch):
    start = Position(5, 5)
    target = Position(8, 5)
    live_planner = {"signature": "active"}

    monkeypatch.setattr(navigation, "calculate_micro_plan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(navigation, "get_available_astar_time_budget", lambda *_args, **_kwargs: 1_000_000)
    monkeypatch.setattr(
        navigation,
        "_resume_anytime_astar",
        lambda *_args, **_kwargs: (
            [(ActionType.CONVEYOR, Direction.EAST)],
            False,
            live_planner,
        ),
    )

    bot = SimpleNamespace(
        bridge_transit_path=None,
        pending_bridge_plan=(start, target),
        bridge_transit_planner_state=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "known_obstacles": set(),
            "temporary_obstacles": {},
            "path": [(ActionType.BRIDGE, target)],
            "planner_state": {"signature": "planner"},
        },
        stats={"double_astar_turns": 0},
        tiled_back_positions=set(),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: start,
        get_current_round=lambda: 30,
        get_team=lambda: 1,
        can_build_bridge=lambda _pos, _target_pos: False,
        build_bridge=lambda _pos, _target_pos: None,
    )

    mode_tiling_back._navigate_and_build(bot, controller, start, Position(10, 5))

    assert bot.pending_bridge_plan == (start, target)
    assert bot.bridge_transit_path is None
    assert bot.bridge_transit_planner_state is live_planner


def test_bridge_to_connected_target_builds_without_transit(monkeypatch):
    start = Position(5, 5)
    target = Position(8, 5)
    built = []
    planner_calls = []

    monkeypatch.setattr(
        navigation,
        "calculate_micro_plan",
        lambda *_args, **_kwargs: planner_calls.append("micro") or [],
    )
    monkeypatch.setattr(
        navigation,
        "_resume_anytime_astar",
        lambda *_args, **_kwargs: planner_calls.append("astar") or ([], False, None),
    )

    bot = SimpleNamespace(
        bridge_transit_path=None,
        pending_bridge_plan=(start, target),
        bridge_transit_planner_state=None,
        bridge_transit_cooldown_until=-1,
        saved_post_bridge_path=[(ActionType.CONVEYOR, Direction.EAST)],
        pathfinding_state={
            "known_obstacles": set(),
            "temporary_obstacles": {},
            "path": [(ActionType.BRIDGE, target)],
            "planner_state": {"signature": "planner"},
        },
        connected_friendly_conveyors={(target.x, target.y): 1},
        stats={"double_astar_turns": 0},
        tiled_back_positions=set(),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: start,
        get_current_round=lambda: 30,
        get_team=lambda: 1,
        can_build_bridge=lambda pos, target_pos: pos == start and target_pos == target,
        build_bridge=lambda pos, target_pos: built.append((pos, target_pos)),
    )

    mode_tiling_back._navigate_and_build(bot, controller, start, target)

    assert built == [(start, target)]
    assert planner_calls == []
    assert bot.pending_bridge_plan is None
    assert bot.bridge_transit_path is None
    assert bot.bridge_transit_planner_state is None
    assert bot.saved_post_bridge_path == []
    assert bot.pathfinding_state["path"] == []
    assert (start.x, start.y) in bot.tiled_back_positions
    assert (target.x, target.y) in bot.tiled_back_positions


def test_tiling_back_executes_pending_bridge_before_connected_completion(monkeypatch):
    start = Position(5, 5)
    target = Position(8, 5)
    built = []
    completion_checks = []

    monkeypatch.setattr(mode_tiling_back, "_update_return_target_while_tiling", lambda *_args: None)
    monkeypatch.setattr(mode_tiling_back, "_ensure_core_slot_exit", lambda *_args: False)
    monkeypatch.setattr(mode_tiling_back, "_is_at_core", lambda *_args: False)
    monkeypatch.setattr(
        mode_tiling_back,
        "_check_connect_to_conveyor",
        lambda *_args: completion_checks.append("check") or True,
    )
    monkeypatch.setattr(mode_tiling_back, "_share_connected_conveyor_marker", lambda *_args: None)
    monkeypatch.setattr(mode_tiling_back, "_share_connected_harvester_marker", lambda *_args: None)
    monkeypatch.setattr(mode_tiling_back, "_navigate_and_build", lambda *_args: built.append("nav"))

    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        pending_build=(ActionType.BRIDGE, start, target),
        pending_bridge_plan=None,
        bridge_transit_path=None,
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"], "planner_state": "stale"},
        grid={(start.x, start.y): {"building": None, "building_team": None}},
        connected_friendly_conveyors={(target.x, target.y): 1},
        claimed_pipeline_positions=set(),
        tiled_back_positions=set(),
        core_pos=Position(0, 0),
        return_target_pos=target,
        return_target_kind=mode_tiling_back.TargetKind.CONVEYOR,
        last_harvester_pos=None,
        shared_connected_conveyor_positions=set(),
        shared_connected_harvester_positions=set(),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: start,
        get_current_round=lambda: 40,
        get_team=lambda *_args: 1,
        get_tile_building_id=lambda *_args: None,
        can_build_bridge=lambda pos, target_pos: pos == start and target_pos == target,
        build_bridge=lambda pos, target_pos: built.append((pos, target_pos)),
    )

    mode_tiling_back.execute(bot, controller)

    assert built == [(start, target)]
    assert completion_checks == ["check"]
    assert bot.pending_build is None
    assert bot.builder_mode == BuilderMode.FINDING_ORE


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


def test_tiling_back_routes_around_enemy_builder_blocking_next_edge(monkeypatch):
    current_pos = Position(5, 5)
    blocked_pos = Position(6, 5)
    monkeypatch.setattr(
        navigation,
        "compute_pathfinding_step",
        lambda *_args, **_kwargs: (
            (ActionType.CONVEYOR, Direction.EAST),
            {
                "known_obstacles": set(),
                "path": [(ActionType.CONVEYOR, Direction.EAST)],
                "temporary_obstacles": {},
                "current_target": (8, 5),
                "last_obstacle_signature": None,
                "last_replan_signature": None,
                "last_replan_round": -1,
                "planner_state": None,
            },
        ),
    )

    bot = SimpleNamespace(
        grid={
            (5, 5): {"env": Environment.EMPTY},
            (6, 5): {
                "entity": EntityType.BUILDER_BOT,
                "entity_team": 2,
                "id": 200,
            },
        },
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        pathfinding_state={
            "known_obstacles": set(),
            "path": [],
            "temporary_obstacles": {},
            "planner_state": None,
            "last_replan_signature": None,
        },
        tiled_back_positions=set(),
        claimed_pipeline_positions=set(),
        shared_pipeline_claim_positions=set(),
        last_pipeline_claim_round=-9999,
        connected_friendly_conveyors={},
        known_friendly_conveyors=set(),
        titanium_locations=set(),
        axionite_locations=set(),
        core_pos=Position(0, 0),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    builds = []
    controller = SimpleNamespace(
        get_position=lambda: current_pos,
        get_team=lambda: 1,
        get_current_round=lambda: 40,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_conveyor=lambda pos, direction: pos == current_pos
        and direction == Direction.EAST,
        build_conveyor=lambda pos, direction: builds.append((pos, direction)),
        can_place_marker=lambda *_args: False,
        can_fire=lambda *_args: False,
        can_destroy=lambda *_args: False,
        can_move=lambda _direction: False,
    )

    mode_tiling_back._navigate_and_build(
        bot,
        controller,
        current_pos,
        Position(8, 5),
    )

    assert builds == [(current_pos, Direction.EAST)]
    assert bot.pathfinding_state["temporary_obstacles"][(6, 5)] == 43


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


def test_clear_obstacles_nondefender_preserves_unconnected_friendly_conveyor():
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
        is_defender_role=False,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    destroyed = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda pos: True,
        destroy=lambda pos: destroyed.append(pos),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert destroyed == []
    assert bot.pathfinding_state["temporary_obstacles"][(5, 5)] == (
        50 + mode_tiling_back.PENDING_BUILD_TEMP_OBSTACLE_TTL
    )
    assert bot.pathfinding_state["path"] == []


def test_clear_obstacles_core_defender_destroys_unconnected_misaligned_friendly_conveyor():
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
        is_defender_role=True,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    destroyed = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_fire=lambda *_args: False,
        can_destroy=lambda pos: True,
        destroy=lambda pos: destroyed.append(pos),
    )

    mode_tiling_back._clear_obstacles_for_conveyor(
        bot,
        controller,
        pos,
        Direction.NORTH,
    )

    assert destroyed == [pos]
    assert (5, 5) not in bot.pathfinding_state["temporary_obstacles"]


def test_clear_obstacles_allows_core_defender_owned_unconnected_conveyor_repair():
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
        is_defender_role=True,
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


def test_pending_conveyor_build_overwrites_unconnected_friendly_pipeline():
    # Mirror of the fixed `_visible_protected_pipeline_at` semantics: an
    # unconnected (orphan) friendly conveyor is no longer "protected",
    # so a pending build should overwrite it rather than marking the
    # tile as a temporary obstacle. This matches jon-6's freely-overwrite
    # behavior for orphan tiles while still keeping live connected
    # lanes protected (covered by
    # `test_pending_conveyor_build_preserves_conflicting_friendly_pipeline`).
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
        claimed_harvesters=set(),
        pathfinding_state={"temporary_obstacles": {}, "path": ["stale"]},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
        core_pos=Position(10, 10),
        known_friendly_conveyors=set(),
        shared_connected_conveyor_positions=set(),
        shared_connected_harvester_positions=set(),
    )
    calls = []
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
        get_team=lambda: 1,
        can_build_conveyor=lambda *_args: True,
        build_conveyor=lambda *_args: calls.append(("build", _args)),
    )

    assert mode_tiling_back._execute_pending_build(bot, controller) is True
    assert any(c[0] == "build" for c in calls)
    assert bot.pending_build is None
    # Not protected → no temp obstacle stamped.
    assert (5, 5) not in bot.pathfinding_state["temporary_obstacles"]


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
    assert bot.grid[(slot.x, slot.y)]["building"] == EntityType.CONVEYOR
    assert bot.grid[(slot.x, slot.y)]["building_team"] == 1
    assert bot.grid[(slot.x, slot.y)]["building_dir"] == utils.direction_toward(
        slot,
        core_tile,
    )
    assert (slot.x, slot.y) in bot.known_friendly_conveyors
    assert mode_tiling_back._is_at_core(
        bot,
        controller,
        slot,
        slot,
        TargetKind.CORE,
    )


def test_tiling_back_completion_waits_for_harvester_delivery_verification(monkeypatch):
    slot = Position(5, 5)
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        core_pos=Position(6, 5),
        return_target_pos=slot,
        return_target_kind=TargetKind.CORE,
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(1, 1),
        last_full_perception_round=40,
        pathfinding_state={"path": [], "temporary_obstacles": {}},
        grid={},
        connected_friendly_conveyors={},
        shared_connected_conveyor_positions=set(),
        shared_connected_harvester_positions=set(),
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: slot,
        get_current_round=lambda: 50,
        get_team=lambda *_args: 1,
    )

    monkeypatch.setattr(mode_tiling_back, "_update_return_target_while_tiling", lambda *_args: None)
    monkeypatch.setattr(mode_tiling_back, "_ensure_core_slot_exit", lambda *_args: False)
    monkeypatch.setattr(mode_tiling_back, "_is_at_core", lambda *_args: True)

    mode_tiling_back.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.pathfinding_state["route_completion_verify_started"] == 50
    assert bot.last_full_perception_round == -1


def test_tiling_back_completion_timeout_queues_route_repair_seed():
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        core_pos=Position(6, 1),
        return_target_pos=Position(5, 1),
        return_target_kind=TargetKind.CORE,
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_planner_state=None,
        bridge_transit_cooldown_until=-1,
        saved_post_bridge_path=[],
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(1, 1),
        last_full_perception_round=40,
        pathfinding_state={
            "path": [("stale",)],
            "planner_state": object(),
            "temporary_obstacles": {},
            "route_completion_verify_started": 30,
        },
        grid={
            (2, 1): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (3, 1): {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (4, 1): {
                "env": Environment.EMPTY,
                "building": None,
                "building_team": None,
            },
        },
        connected_friendly_conveyors={},
        ore_target_blacklist={},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(5, 1),
        get_current_round=lambda: 42,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
    )

    completed = mode_tiling_back._complete_tiling_back_or_wait_for_verification(
        bot,
        controller,
        "core completion",
    )

    assert completed is True
    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.pathfinding_state["route_completion_repair_target"] == (4, 1)
    assert bot.pathfinding_state["route_completion_repair_attempts"] == 1
    assert "route_completion_verify_started" not in bot.pathfinding_state
    assert bot.pathfinding_state["path"] == []
    assert bot.pathfinding_state["planner_state"] is None
    assert bot.ore_target_blacklist == {}


def test_tiling_back_completion_timeout_abandons_shallow_unverified_route():
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        core_pos=Position(6, 1),
        return_target_pos=Position(5, 1),
        return_target_kind=TargetKind.CORE,
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_planner_state=None,
        bridge_transit_cooldown_until=-1,
        saved_post_bridge_path=[],
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(1, 1),
        last_full_perception_round=40,
        pathfinding_state={
            "path": [("stale",)],
            "planner_state": object(),
            "temporary_obstacles": {},
            "route_completion_verify_started": 30,
        },
        grid={
            (2, 1): {
                "env": Environment.EMPTY,
                "building": None,
                "building_team": None,
            },
        },
        connected_friendly_conveyors={},
        ore_target_blacklist={},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: Position(5, 1),
        get_current_round=lambda: 42,
        get_team=lambda *_args: 1,
        get_map_width=lambda: 20,
        get_map_height=lambda: 20,
    )

    completed = mode_tiling_back._complete_tiling_back_or_wait_for_verification(
        bot,
        controller,
        "core completion",
    )

    assert completed is True
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert "route_completion_repair_target" not in bot.pathfinding_state
    assert bot.ore_target_blacklist[(1, 1)] > 42


def test_route_completion_repair_moves_without_reverse_building(monkeypatch):
    calls = []
    bot = SimpleNamespace(
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        pathfinding_state={
            "path": [("stale",)],
            "planner_state": object(),
            "last_replan_signature": object(),
            "route_completion_repair_target": (4, 1),
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 50,
    )

    monkeypatch.setattr(
        navigation,
        "move_towards",
        lambda _bot, _ct, target: calls.append(target) or True,
    )
    monkeypatch.setattr(
        navigation,
        "consume_shared_progress_stall",
        lambda _bot: False,
    )

    consumed = mode_tiling_back._handle_route_completion_repair(
        bot,
        controller,
        Position(5, 1),
    )

    assert consumed is True
    assert calls == [Position(4, 1)]
    assert bot.pending_build is None
    assert bot.pathfinding_state["route_completion_repair_target"] == (4, 1)

    consumed = mode_tiling_back._handle_route_completion_repair(
        bot,
        controller,
        Position(4, 1),
    )

    assert consumed is False
    assert "route_completion_repair_target" not in bot.pathfinding_state
    assert bot.pathfinding_state["path"] == []
    assert bot.pathfinding_state["planner_state"] is None
    assert bot.pathfinding_state["last_replan_signature"] is None


def test_tiling_back_completion_accepts_locally_verified_harvester_route(monkeypatch):
    slot = Position(4, 1)
    bot = SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        core_pos=Position(5, 1),
        return_target_pos=slot,
        return_target_kind=TargetKind.CORE,
        pending_build=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(1, 1),
        last_full_perception_round=40,
        pathfinding_state={
            "path": [],
            "temporary_obstacles": {},
            "tiling_back_tried_core_lane_slots": {(4, 1)},
        },
        grid={
            (2, 1): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (3, 1): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
            (4, 1): {
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            },
        },
        connected_friendly_conveyors={},
        shared_connected_conveyor_positions=set(),
        shared_connected_harvester_positions=set(),
        tiling_force_core_return=True,
        tiling_prefer_core_return=True,
        tiling_core_approach_full=False,
        core_return_target_pos=slot,
        core_lane_slot_pos=slot,
        core_lane_core_tile_pos=Position(5, 1),
        core_lane_exit_built=True,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_position=lambda: slot,
        get_current_round=lambda: 50,
        get_team=lambda *_args: 1,
    )

    monkeypatch.setattr(mode_tiling_back, "_update_return_target_while_tiling", lambda *_args: None)
    monkeypatch.setattr(mode_tiling_back, "_ensure_core_slot_exit", lambda *_args: False)
    monkeypatch.setattr(mode_tiling_back, "_is_at_core", lambda *_args: True)

    mode_tiling_back.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert "route_completion_verify_started" not in bot.pathfinding_state
    assert "tiling_back_tried_core_lane_slots" not in bot.pathfinding_state
    assert bot.tiling_prefer_core_return is False


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


def _make_rotation_bot(initial_slot: Position) -> SimpleNamespace:
    return SimpleNamespace(
        builder_mode=BuilderMode.TILING_BACK,
        tiling_back_origin_kind="HARVESTER",
        last_harvester_pos=Position(10, 10),
        core_pos=Position(10, 10),
        core_lane_slot_pos=initial_slot,
        core_lane_core_tile_pos=Position(10, 10 + (1 if initial_slot.y > 10 else -1)),
        core_lane_exit_built=False,
        core_return_target_pos=Position(10, 10 + (1 if initial_slot.y > 10 else -1)),
        return_target_pos=initial_slot,
        return_target_dist_manhatten=5,
        return_target_kind=TargetKind.CORE,
        tiling_force_core_return=True,
        tiling_prefer_core_return=True,
        tiling_core_approach_full=False,
        ore_target_blacklist={},
        pending_build=None,
        pending_axionite_plan=None,
        pending_bridge_plan=None,
        bridge_transit_path=None,
        bridge_transit_cooldown_until=-1,
        nearest_conveyor_pos=None,
        nearest_conveyor_dist_manhatten=float("inf"),
        saved_post_bridge_path=[],
        last_return_target_refresh_round=-1,
        pathfinding_state={
            "path": ["stale"],
            "planner_state": {"stale": True},
            "last_replan_signature": "stale",
        },
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )


def test_tiling_back_nav_stall_rotates_core_lane_slot_at_fallback_threshold():
    """When a force_core_return builder stalls at DIRECT_CORE_FALLBACK_STALL_LIMIT
    turns, the current core lane slot should be retired, pathfinding state reset,
    and TILING_BACK continue so A* can retarget a different approach slot next turn.
    """
    initial_slot = Position(12, 12)
    bot = _make_rotation_bot(initial_slot)
    controller = SimpleNamespace(
        get_current_round=lambda: 100,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
    )
    stuck_pos = Position(5, 5)

    result = False
    for i in range(mode_tiling_back.DIRECT_CORE_FALLBACK_STALL_LIMIT):
        result = mode_tiling_back._note_nav_stall(bot, controller, stuck_pos, stuck_pos)
        assert result is False, f"Should not abandon on turn {i + 1}"

    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.core_lane_slot_pos is None
    tried = bot.pathfinding_state.get("tiling_back_tried_core_lane_slots")
    assert tried == {(initial_slot.x, initial_slot.y)}
    # Nav stall counters cleared so the next turn gets a fresh A* attempt.
    assert "tiling_back_nav_stall_turns" not in bot.pathfinding_state
    assert bot.pathfinding_state["path"] == []
    assert bot.pathfinding_state["planner_state"] is None
    # Harvester NOT blacklisted — rotation is recoverable, not a failure.
    assert (10, 10) not in bot.ore_target_blacklist


def test_tiling_back_nav_stall_abandons_after_slot_rotation_exhausted():
    """After rotating through all approach slots, a stuck builder must still
    abandon once the hard NAV_STALL_LIMIT is reached."""
    initial_slot = Position(12, 12)
    bot = _make_rotation_bot(initial_slot)
    # Pre-populate the tried set with every approach slot except the current,
    # so exactly one rotation is possible.
    all_slots = mode_tiling_back._core_approach_slots(  # noqa: SLF001
        bot,
        SimpleNamespace(get_map_width=lambda: 30, get_map_height=lambda: 30),
    )
    tried = {
        (slot.x, slot.y)
        for slot in all_slots
        if (slot.x, slot.y) != (initial_slot.x, initial_slot.y)
    }
    bot.pathfinding_state["tiling_back_tried_core_lane_slots"] = tried

    controller = SimpleNamespace(
        get_current_round=lambda: 200,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
    )
    stuck_pos = Position(5, 5)

    # Stall until rotation would fire: no rotation is possible (only
    # one slot left, which is the current one), so counter keeps climbing.
    for _ in range(mode_tiling_back.NAV_STALL_LIMIT - 1):
        result = mode_tiling_back._note_nav_stall(bot, controller, stuck_pos, stuck_pos)
        assert result is False

    result = mode_tiling_back._note_nav_stall(bot, controller, stuck_pos, stuck_pos)
    assert result is True
    assert bot.builder_mode == BuilderMode.FINDING_ORE
    # Abandon clears the tried set for a future TILING_BACK entry.
    assert "tiling_back_tried_core_lane_slots" not in bot.pathfinding_state


def test_tiling_back_rotation_skips_tried_slots_on_reassignment():
    """_assign_core_lane_slot must skip any slot in the tried set, so a
    rotated builder picks a different approach slot on the next turn."""
    bot = _make_rotation_bot(Position(12, 12))
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.spawn_pos = Position(5, 5)
    bot.grid = {}
    bot.claimed_pipeline_positions = set()
    bot.shared_pipeline_claim_positions = set()
    bot.connected_friendly_conveyors = {}

    controller = SimpleNamespace(
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_id=lambda: 7,
        get_team=lambda: 0,
    )

    assigned_first = mode_tiling_back._assign_core_lane_slot(  # noqa: SLF001
        bot, controller, origin=Position(5, 5)
    )
    assert assigned_first is not None
    first_key = (assigned_first.x, assigned_first.y)

    # Simulate a rotation: record the slot as tried and force reassignment.
    bot.pathfinding_state["tiling_back_tried_core_lane_slots"] = {first_key}
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None

    assigned_second = mode_tiling_back._assign_core_lane_slot(  # noqa: SLF001
        bot, controller, origin=Position(5, 5)
    )
    assert assigned_second is not None
    assert (assigned_second.x, assigned_second.y) != first_key


def test_tiling_back_rotation_returns_none_when_all_slots_exhausted():
    """When every approach slot is in the tried set, _assign_core_lane_slot
    must return None so the caller falls through to default targeting."""
    bot = _make_rotation_bot(Position(12, 12))
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.spawn_pos = Position(5, 5)
    bot.grid = {}
    bot.claimed_pipeline_positions = set()
    bot.shared_pipeline_claim_positions = set()
    bot.connected_friendly_conveyors = {}

    controller = SimpleNamespace(
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_id=lambda: 7,
        get_team=lambda: 0,
    )

    all_slots = mode_tiling_back._core_approach_slots(bot, controller)  # noqa: SLF001
    bot.pathfinding_state["tiling_back_tried_core_lane_slots"] = {
        (slot.x, slot.y) for slot in all_slots
    }

    assigned = mode_tiling_back._assign_core_lane_slot(  # noqa: SLF001
        bot, controller, origin=Position(5, 5)
    )
    assert assigned is None
    assert bot.core_lane_slot_pos is None


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
        ore_target_blacklist={(5, 5): 999},
        ore_target_state={"ore": (5, 5), "access": (5, 6), "stuck_turns": 3},
        explore_target_chunk=(2, 2),
        explore_target_pos=Position(8, 8),
        pathfinding_state={"path": [(ActionType.CONVEYOR, Direction.NORTH)], "planner_state": {"sig": 1}, "last_replan_signature": "old"},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    controller = SimpleNamespace(
        get_current_round=lambda: 10 + mode_assaulting.ASSAULT_ECONOMY_FALLBACK_TURNS + 1,
    )

    mode_assaulting._maybe_transition_to_economy(bot, controller)

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert bot.is_assault_role is False
    # Verify stale state was cleared
    assert len(bot.ore_target_blacklist) == 0
    assert bot.ore_target_state["ore"] is None
    assert bot.explore_target_chunk is None
    assert bot.pathfinding_state["path"] == []
    assert bot.pathfinding_state["planner_state"] is None


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
    """After the explicit opening rusher, later spawns are builders."""
    from core_bot import CoreBot

    core = CoreBot()
    controller_early = SimpleNamespace(
        get_global_resources=lambda: (200, 0),
        get_current_round=lambda: 50,
    )
    assert core._assault_quota(controller_early) == 0

    controller_late = SimpleNamespace(
        get_global_resources=lambda: (200, 0),
        get_current_round=lambda: 100,
    )
    assert core._assault_quota(controller_late) == 0

    controller_late_low = SimpleNamespace(
        get_global_resources=lambda: (50, 0),
        get_current_round=lambda: 100,
    )
    assert core._assault_quota(controller_late_low) == 0


def test_core_opening_frame_is_seat_agnostic():
    from core_bot import CoreBot

    core = CoreBot()
    upper_left = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )
    lower_right = SimpleNamespace(
        get_position=lambda: Position(30, 30),
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
    )

    assert core._opening_orientation_frame(upper_left)["inward"] == Direction.EAST
    assert core._opening_orientation_frame(upper_left)["rusher"] == Direction.SOUTHEAST
    assert core._opening_orientation_frame(lower_right)["inward"] == Direction.WEST
    assert core._opening_orientation_frame(lower_right)["rusher"] == Direction.NORTHWEST


def test_core_opening_spawns_three_builders_defender_then_rusher(monkeypatch):
    from core_bot import CoreBot

    core = CoreBot()
    monkeypatch.setattr(
        core,
        "_opening_builder_spawn_directions",
        lambda _ct: [Direction.NORTH, Direction.SOUTH, Direction.WEST],
    )
    spawns = []
    current_round = {"value": 1}
    controller = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
        get_nearby_entities=lambda: [],
        get_entity_type=lambda _entity_id=None: EntityType.CORE,
        get_id=lambda: 1,
        get_team=lambda _entity_id=None: 1,
        get_unit_count=lambda: 1 + len(spawns),
        get_current_round=lambda: current_round["value"],
        can_spawn=lambda _pos: True,
        spawn_builder=lambda pos: spawns.append(pos),
    )

    for round_num in range(1, 6):
        current_round["value"] = round_num
        core.run(controller)

    assert spawns == [
        Position(10, 9),
        Position(10, 11),
        Position(9, 10),
        Position(11, 10),
        Position(11, 11),
    ]


def test_core_opening_builder_roles_fall_back_when_preferred_cardinals_blocked(monkeypatch):
    import core_bot
    from core_bot import CoreBot

    core = CoreBot()
    monkeypatch.setattr(core_bot.random, "shuffle", lambda _items: None)
    spawns = []
    current_round = {"value": 1}
    core_pos = Position(10, 10)
    blocked_builder_cardinals = {
        core_pos.add(Direction.SOUTH),
        core_pos.add(Direction.NORTH),
        core_pos.add(Direction.WEST),
    }

    def can_spawn(pos: Position) -> bool:
        if pos in blocked_builder_cardinals:
            return False
        return pos not in spawns

    controller = SimpleNamespace(
        get_position=lambda: core_pos,
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
        get_nearby_entities=lambda: [],
        get_entity_type=lambda _entity_id=None: EntityType.CORE,
        get_id=lambda: 1,
        get_team=lambda _entity_id=None: 1,
        get_unit_count=lambda: 1 + len(spawns),
        get_current_round=lambda: current_round["value"],
        can_spawn=can_spawn,
        spawn_builder=lambda pos: spawns.append(pos),
    )

    for round_num in range(1, 6):
        current_round["value"] = round_num
        core.run(controller)

    assert len(spawns) == 5
    assert all(pos not in blocked_builder_cardinals for pos in spawns[:3])
    assert spawns[3] == Position(11, 10)
    assert spawns[4] == Position(11, 11)


def test_core_late_spawn_uses_higher_live_cap_and_high_bank():
    from core_bot import CoreBot, OPENING_ROLE_SEQUENCE

    core = CoreBot()
    core.builder_counter = len(OPENING_ROLE_SEQUENCE)
    core.last_spawn_turn = 0
    spawns = []
    controller = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
        get_nearby_entities=lambda: [],
        get_entity_type=lambda _entity_id=None: EntityType.CORE,
        get_id=lambda: 1,
        get_team=lambda _entity_id=None: 1,
        get_unit_count=lambda: 13,
        get_current_round=lambda: 20,
        get_global_resources=lambda: (5000, 0),
        can_spawn=lambda _pos: True,
        spawn_builder=lambda pos: spawns.append(pos),
    )

    core.run(controller)

    assert len(spawns) == 1


def test_core_late_spawn_still_respects_live_cap():
    from core_bot import CoreBot, OPENING_ROLE_SEQUENCE

    core = CoreBot()
    core.builder_counter = len(OPENING_ROLE_SEQUENCE)
    core.last_spawn_turn = 0
    spawns = []
    controller = SimpleNamespace(
        get_position=lambda: Position(10, 10),
        get_map_width=lambda: 40,
        get_map_height=lambda: 40,
        get_nearby_entities=lambda: [],
        get_entity_type=lambda _entity_id=None: EntityType.CORE,
        get_id=lambda: 1,
        get_team=lambda _entity_id=None: 1,
        get_unit_count=lambda: 17,
        get_current_round=lambda: 20,
        get_global_resources=lambda: (5000, 0),
        can_spawn=lambda _pos: True,
        spawn_builder=lambda pos: spawns.append(pos),
    )

    core.run(controller)

    assert spawns == []


def test_core_scan_markers_caches_team_and_map_dimensions():
    from core_bot import CoreBot

    counts = {"team_self": 0, "width": 0, "height": 0}
    marker_values = {
        11: marker.create_ore_marker(Position(7, 8), 40, 30, 30),
        12: marker.create_connected_conveyor_marker(Position(6, 6), 40, 30, 30),
    }

    def get_team(entity_id=None):
        if entity_id is None:
            counts["team_self"] += 1
            return 1
        return 1

    controller = SimpleNamespace(
        get_nearby_entities=lambda: [11, 12],
        get_entity_type=lambda _entity_id: EntityType.MARKER,
        get_team=get_team,
        get_marker_value=lambda entity_id: marker_values[entity_id],
        get_map_width=lambda: counts.__setitem__("width", counts["width"] + 1) or 30,
        get_map_height=lambda: counts.__setitem__("height", counts["height"] + 1) or 30,
    )
    core = CoreBot()

    core._scan_markers(controller)  # noqa: SLF001

    assert core.titanium_locations == {Position(7, 8)}
    assert core.has_connected_economy is True
    assert counts == {"team_self": 1, "width": 1, "height": 1}


def test_core_scan_markers_skips_map_dimensions_without_friendly_markers():
    from core_bot import CoreBot

    calls = []
    controller = SimpleNamespace(
        get_nearby_entities=lambda: [11],
        get_entity_type=lambda _entity_id: EntityType.HARVESTER,
        get_team=lambda _entity_id=None: 1,
        get_map_width=lambda: calls.append("width") or 30,
        get_map_height=lambda: calls.append("height") or 30,
    )
    core = CoreBot()

    core._scan_markers(controller)  # noqa: SLF001

    assert calls == []


def test_axionite_planner_skips_when_economy_not_ready():
    import axionite_planner  # noqa: PLC0415

    bot = SimpleNamespace(
        grid={},
        core_pos=Position(10, 10),
        connected_friendly_conveyors={},
        titanium_locations=set(),
        axionite_locations=set(),
    )
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_global_resources=lambda: (50, 0),
    )
    plan = axionite_planner.plan_axionite_foundry_placement(
        bot,
        controller,
        Position(5, 5),
    )
    assert plan is None


def test_axionite_planner_finds_placement_with_adjacent_ti_lane():
    import axionite_planner  # noqa: PLC0415

    ax_pos = Position(5, 5)
    # Build a grid layout:
    #   (5, 5)  ax ore
    #   (5, 6)  raw-ax conveyor tile — EMPTY, will be built
    #   (5, 7)  foundry tile — EMPTY, will be built
    #   (6, 7)  connected Ti conveyor pointing WEST into foundry
    #   (5, 8)  empty tile — output toward core (10, 10)
    connected = {
        (6, 7): 0,  # load placeholder; presence is the check
    }
    grid = {
        (5, 5): {"env": Environment.ORE_AXIONITE},
        (5, 6): {"env": Environment.EMPTY},
        (5, 7): {"env": Environment.EMPTY},
        (6, 7): {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.WEST,
        },
        (5, 8): {"env": Environment.EMPTY},
    }
    # Stub enough connected-friendly-conveyor entries to satisfy the
    # readiness gate (needs at least 8 by current constants).
    connected = {
        (6, 7 + i): 0 for i in range(-3, 5)
    }
    assert len(connected) >= utils.AXIONITE_MIN_CONNECTED_CONVEYORS
    bot = SimpleNamespace(
        grid=grid,
        core_pos=Position(10, 10),
        connected_friendly_conveyors=connected,
        titanium_locations={ax_pos},
        axionite_locations={ax_pos},
    )
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_global_resources=lambda: (500, 0),
    )
    plan = axionite_planner.plan_axionite_foundry_placement(
        bot,
        controller,
        ax_pos,
    )
    assert plan is not None
    assert plan.ax_ore_pos == ax_pos
    assert plan.foundry_pos == Position(5, 7)
    assert plan.raw_ax_conveyor_pos == Position(5, 6)
    assert plan.ti_input_conveyor_pos == Position(6, 7)
    # Refined output conveyor must be empty cardinal neighbour of the
    # foundry that is NOT the ax source or the ti input, preferring
    # the one closest to the core at (10, 10).
    assert plan.refined_output_conveyor_pos in {
        Position(5, 8),
        Position(4, 7),
    }


def test_axionite_eligibility_waits_for_ready_titanium_lane():
    ti_pos = Position(3, 3)
    ax_pos = Position(5, 5)
    bot = SimpleNamespace(
        titanium_locations={ti_pos},
        axionite_locations={ax_pos},
        connected_friendly_conveyors={},
    )
    low_controller = SimpleNamespace(get_global_resources=lambda: (500, 0))

    assert utils.get_eligible_ore_locations(bot, low_controller) == [ti_pos]

    bot.connected_friendly_conveyors = {
        (10, 10 + i): 0 for i in range(utils.AXIONITE_MIN_CONNECTED_CONVEYORS)
    }
    ready_controller = SimpleNamespace(
        get_global_resources=lambda: (utils.AXIONITE_MIN_TI_RESERVE, 0)
    )

    eligible = set(utils.get_eligible_ore_locations(bot, ready_controller))
    assert eligible == {ti_pos, ax_pos}


def test_axionite_planner_requires_current_access_tile_for_executor():
    import axionite_planner  # noqa: PLC0415

    ax_pos = Position(5, 5)
    current_pos = Position(5, 6)
    grid = {
        (5, 5): {"env": Environment.ORE_AXIONITE},
        (5, 6): {"env": Environment.EMPTY, "entity": EntityType.BUILDER_BOT},
        (5, 7): {"env": Environment.EMPTY},
        (6, 7): {
            "env": Environment.EMPTY,
            "building": EntityType.CONVEYOR,
            "building_team": 1,
            "building_dir": Direction.WEST,
        },
        (4, 7): {"env": Environment.EMPTY},
        # This tile is closer to the core but is too far from current_pos
        # for the one-tile local executor, so the constrained planner
        # must choose the west-side output instead.
        (5, 8): {"env": Environment.EMPTY},
    }
    bot = SimpleNamespace(
        grid=grid,
        core_pos=Position(10, 10),
        connected_friendly_conveyors={
            (6, 7 + i): 0 for i in range(-3, 5)
        },
    )
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        get_global_resources=lambda: (500, 0),
    )

    rejected = axionite_planner.plan_axionite_foundry_placement(
        bot,
        controller,
        ax_pos,
        builder_pos=Position(4, 5),
    )
    plan = axionite_planner.plan_axionite_foundry_placement(
        bot,
        controller,
        ax_pos,
        builder_pos=current_pos,
    )

    assert rejected is None
    assert plan is not None
    assert plan.raw_ax_conveyor_pos == current_pos
    assert plan.foundry_pos == Position(5, 7)
    assert plan.refined_output_conveyor_pos == Position(4, 7)


def test_pending_foundry_build_executes_and_clears_state():
    foundry_pos = Position(5, 7)
    bot = SimpleNamespace(
        pending_build=(ActionType.FOUNDRY, foundry_pos),
        grid={(5, 7): {"env": Environment.EMPTY}},
        pathfinding_state={},
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    calls = []
    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 20,
        can_build_foundry=lambda pos: pos == foundry_pos,
        build_foundry=lambda pos: calls.append(("foundry", pos)),
    )

    assert mode_tiling_back._execute_pending_build(bot, controller) is True
    assert calls == [("foundry", foundry_pos)]
    assert bot.pending_build is None


def test_axionite_splice_executor_builds_local_parts_before_return():
    import axionite_planner  # noqa: PLC0415

    raw_pos = Position(5, 6)
    foundry_pos = Position(5, 7)
    output_pos = Position(4, 7)
    plan = axionite_planner.FoundryPlacement(
        ax_ore_pos=Position(5, 5),
        foundry_pos=foundry_pos,
        raw_ax_conveyor_pos=raw_pos,
        raw_ax_conveyor_dir=Direction.NORTH,
        ti_input_conveyor_pos=Position(6, 7),
        refined_output_conveyor_pos=output_pos,
        refined_output_conveyor_dir=Direction.EAST,
    )
    bot = SimpleNamespace(
        pending_axionite_plan=plan,
        pending_build=None,
        grid={
            (5, 6): {"env": Environment.EMPTY},
            (5, 7): {"env": Environment.EMPTY},
            (4, 7): {"env": Environment.EMPTY},
        },
        tiled_back_positions=set(),
        claimed_pipeline_positions=set(),
        shared_pipeline_claim_positions=set(),
        last_pipeline_claim_round=-9999,
        connected_friendly_conveyors={},
        known_friendly_conveyors=set(),
        titanium_locations=set(),
        axionite_locations={Position(5, 5)},
        core_pos=Position(10, 10),
        pathfinding_state={"path": ["stale"], "planner_state": object()},
        return_target_pos=Position(0, 0),
        return_target_dist_manhatten=99,
        return_target_kind=TargetKind.CONVEYOR,
        tiling_back_origin_kind="HARVESTER",
        tiling_force_core_return=False,
        tiling_prefer_core_return=False,
        logger=SimpleNamespace(log=lambda *_args, **_kwargs: None),
    )
    current = {"pos": raw_pos}
    calls = []

    def can_build_conveyor(pos, direction):
        return (
            (pos, direction) == (raw_pos, Direction.NORTH)
            and "raw" not in calls
        ) or (
            (pos, direction) == (output_pos, Direction.EAST)
            and "output" not in calls
        )

    def build_conveyor(pos, direction):
        if pos == raw_pos:
            calls.append("raw")
            bot.grid[(5, 6)] = {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.NORTH,
            }
        elif pos == output_pos:
            calls.append("output")
            bot.grid[(4, 7)] = {
                "env": Environment.EMPTY,
                "building": EntityType.CONVEYOR,
                "building_team": 1,
                "building_dir": Direction.EAST,
            }

    def build_foundry(pos):
        calls.append("foundry")
        bot.grid[(5, 7)] = {
            "env": Environment.EMPTY,
            "building": EntityType.FOUNDRY,
            "building_team": 1,
        }

    def move(direction):
        calls.append(("move", direction))
        current["pos"] = output_pos

    controller = SimpleNamespace(
        get_team=lambda: 1,
        get_current_round=lambda: 20,
        get_map_width=lambda: 30,
        get_map_height=lambda: 30,
        can_build_conveyor=can_build_conveyor,
        build_conveyor=build_conveyor,
        can_build_foundry=lambda pos: pos == foundry_pos and "foundry" not in calls,
        build_foundry=build_foundry,
        can_place_marker=lambda *_args: False,
        can_fire=lambda *_args: False,
        can_destroy=lambda *_args: False,
        can_move=lambda direction: direction == utils.direction_toward(raw_pos, output_pos),
        move=move,
    )

    assert mode_tiling_back._execute_pending_axionite_plan(bot, controller, raw_pos)
    assert mode_tiling_back._execute_pending_axionite_plan(bot, controller, raw_pos)
    assert mode_tiling_back._execute_pending_axionite_plan(bot, controller, raw_pos)
    assert mode_tiling_back._execute_pending_axionite_plan(bot, controller, raw_pos)
    assert current["pos"] == output_pos
    assert mode_tiling_back._execute_pending_axionite_plan(bot, controller, output_pos) is False

    assert calls == ["raw", "foundry", "output", ("move", utils.direction_toward(raw_pos, output_pos))]
    assert bot.pending_axionite_plan is None
    assert bot.tiling_back_origin_kind == "AXIONITE_REFINED_OUTPUT"
    assert bot.tiling_force_core_return is True
    assert bot.return_target_kind == TargetKind.CORE
