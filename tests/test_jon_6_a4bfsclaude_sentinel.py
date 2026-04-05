from __future__ import annotations

import importlib
import sys
from pathlib import Path

from cambc import EntityType, Environment, Position


JON_6_A4_BFS_ROOT = Path(__file__).resolve().parent.parent / "bots" / "jon-6-a4bfsclaude"
for module_name in ("assault", "main", "sentinel_bot"):
    sys.modules.pop(module_name, None)
if str(JON_6_A4_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A4_BFS_ROOT))
importlib.invalidate_caches()

import main as main_module
from sentinel_bot import SentinelBot


class _StubSentinelController:
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


class _StubPlayerController:
    def get_entity_type(self):
        return EntityType.SENTINEL


def test_player_instantiates_sentinel_controller(monkeypatch):
    created: list[object] = []

    class _FakeSentinelBot:
        def __init__(self):
            created.append(self)

        def run(self, _ct):
            return

    monkeypatch.setattr(main_module, "SentinelBot", _FakeSentinelBot)
    player = main_module.Player()

    player.run(_StubPlayerController())

    assert len(created) == 1
    assert player.robot is created[0]


def test_sentinel_fires_highest_priority_legal_target_and_ignores_anchor_harvester():
    controller = _StubSentinelController()

    SentinelBot().run(controller)

    assert controller.fired_at == Position(7, 5)


def test_sentinel_holds_when_only_anchor_harvester_is_legal():
    controller = _StubSentinelController(legal_targets={(5, 4)})

    SentinelBot().run(controller)

    assert controller.fired_at is None


def test_sentinel_prefers_core_once_only_one_local_logistics_target_remains():
    controller = _StubSentinelController(legal_targets={(6, 4), (8, 5)})
    del controller.entities[13]

    SentinelBot().run(controller)

    assert controller.fired_at == Position(8, 5)


def test_sentinel_skips_enemy_building_tile_if_friendly_builder_is_standing_on_it():
    controller = _StubSentinelController(legal_targets={(6, 4), (8, 5)})
    del controller.entities[13]
    controller.entities[21] = {
        "team": 1,
        "type": EntityType.BUILDER_BOT,
        "position": Position(6, 4),
        "hp": 10,
    }

    SentinelBot().run(controller)

    assert controller.fired_at == Position(8, 5)


def test_sentinel_holds_when_only_legal_enemy_tile_is_occupied_by_friendly_builder():
    controller = _StubSentinelController(legal_targets={(6, 4)})
    del controller.entities[13]
    controller.entities[21] = {
        "team": 1,
        "type": EntityType.BUILDER_BOT,
        "position": Position(6, 4),
        "hp": 10,
    }

    SentinelBot().run(controller)

    assert controller.fired_at is None
