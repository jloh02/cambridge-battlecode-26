"""Runtime protobuf schema for `.replay26` and `.map26` files.

The official `cambc` package ships replay files and a browser visualiser, but
it does not expose a Python replay decoder. The visualiser bundle contains the
protobuf reflection schema, so this module reconstructs that schema in Python
using `google.protobuf` dynamic descriptors.

This keeps replay tooling local to the repository and avoids adding any bot
runtime dependency beyond the dev-only `protobuf` package.
"""

from __future__ import annotations

from functools import lru_cache

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


LABEL_OPTIONAL = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
LABEL_REPEATED = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

TYPE_BOOL = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
TYPE_ENUM = descriptor_pb2.FieldDescriptorProto.TYPE_ENUM
TYPE_INT32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
TYPE_MESSAGE = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
TYPE_STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
TYPE_UINT32 = descriptor_pb2.FieldDescriptorProto.TYPE_UINT32


def _add_enum(file_proto: descriptor_pb2.FileDescriptorProto, name: str, values: list[tuple[str, int]]) -> None:
    enum_proto = file_proto.enum_type.add()
    enum_proto.name = name
    for value_name, number in values:
        value_proto = enum_proto.value.add()
        value_proto.name = value_name
        value_proto.number = number


def _add_message(file_proto: descriptor_pb2.FileDescriptorProto, name: str) -> descriptor_pb2.DescriptorProto:
    message_proto = file_proto.message_type.add()
    message_proto.name = name
    return message_proto


def _add_field(
    message_proto: descriptor_pb2.DescriptorProto,
    *,
    name: str,
    number: int,
    field_type: int,
    label: int = LABEL_OPTIONAL,
    type_name: str | None = None,
    proto3_optional: bool = False,
) -> None:
    field_proto = message_proto.field.add()
    field_proto.name = name
    field_proto.number = number
    field_proto.label = label
    field_proto.type = field_type
    if type_name is not None:
        field_proto.type_name = type_name
    if proto3_optional:
        oneof_proto = message_proto.oneof_decl.add()
        oneof_proto.name = f"_{name}"
        field_proto.proto3_optional = True
        field_proto.oneof_index = len(message_proto.oneof_decl) - 1


def _build_file_descriptor() -> descriptor_pb2.FileDescriptorProto:
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "battlecode_replay.proto"
    file_proto.package = "battlecode"
    file_proto.syntax = "proto3"

    _add_enum(file_proto, "Team", [("TEAM_A", 0), ("TEAM_B", 1)])
    _add_enum(
        file_proto,
        "Direction",
        [
            ("DIR_CENTRE", 0),
            ("DIR_NORTH", 1),
            ("DIR_NORTHEAST", 2),
            ("DIR_EAST", 3),
            ("DIR_SOUTHEAST", 4),
            ("DIR_SOUTH", 5),
            ("DIR_SOUTHWEST", 6),
            ("DIR_WEST", 7),
            ("DIR_NORTHWEST", 8),
        ],
    )
    _add_enum(
        file_proto,
        "ResourceType",
        [
            ("RESOURCE_NONE", 0),
            ("RESOURCE_TITANIUM", 1),
            ("RESOURCE_RAW_AXIONITE", 2),
            ("RESOURCE_REFINED_AXIONITE", 3),
        ],
    )
    _add_enum(
        file_proto,
        "Environment",
        [
            ("ENV_EMPTY", 0),
            ("ENV_WALL", 1),
            ("ENV_ORE_TITANIUM", 2),
            ("ENV_ORE_AXIONITE", 3),
        ],
    )

    replay = _add_message(file_proto, "Replay")
    _add_field(replay, name="map", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.Map")
    _add_field(
        replay,
        name="turns",
        number=3,
        field_type=TYPE_MESSAGE,
        label=LABEL_REPEATED,
        type_name=".battlecode.Turn",
    )
    _add_field(
        replay,
        name="winner",
        number=4,
        field_type=TYPE_ENUM,
        type_name=".battlecode.Team",
        proto3_optional=True,
    )

    map_proto = _add_message(file_proto, "Map")
    _add_field(map_proto, name="width", number=1, field_type=TYPE_INT32)
    _add_field(map_proto, name="height", number=2, field_type=TYPE_INT32)
    _add_field(
        map_proto,
        name="rows",
        number=3,
        field_type=TYPE_MESSAGE,
        label=LABEL_REPEATED,
        type_name=".battlecode.TileRow",
    )
    _add_field(
        map_proto,
        name="cores",
        number=4,
        field_type=TYPE_MESSAGE,
        label=LABEL_REPEATED,
        type_name=".battlecode.CorePosition",
    )

    tile_row = _add_message(file_proto, "TileRow")
    _add_field(
        tile_row,
        name="tiles",
        number=1,
        field_type=TYPE_ENUM,
        label=LABEL_REPEATED,
        type_name=".battlecode.Environment",
    )

    players = _add_message(file_proto, "Players")
    _add_field(players, name="a", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.Player")
    _add_field(players, name="b", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.Player")

    player = _add_message(file_proto, "Player")
    _add_field(player, name="titanium", number=1, field_type=TYPE_INT32)
    _add_field(player, name="axionite", number=2, field_type=TYPE_INT32)
    _add_field(player, name="resourcesCollected", number=3, field_type=TYPE_INT32)
    _add_field(player, name="titaniumCollected", number=4, field_type=TYPE_INT32)
    _add_field(player, name="axioniteCollected", number=5, field_type=TYPE_INT32)

    turn = _add_message(file_proto, "Turn")
    _add_field(
        turn,
        name="updates",
        number=1,
        field_type=TYPE_MESSAGE,
        label=LABEL_REPEATED,
        type_name=".battlecode.Update",
    )

    update = _add_message(file_proto, "Update")
    _add_field(update, name="placeEntity", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.PlaceEntity")
    _add_field(update, name="moveBuilderBot", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.MoveBuilderBot")
    _add_field(update, name="removeEntity", number=3, field_type=TYPE_MESSAGE, type_name=".battlecode.RemoveEntity")
    _add_field(
        update,
        name="distributeResources",
        number=4,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.DistributeResources",
    )
    _add_field(update, name="updateHp", number=5, field_type=TYPE_MESSAGE, type_name=".battlecode.UpdateHp")
    _add_field(
        update,
        name="updatePlayers",
        number=6,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.UpdatePlayers",
    )
    _add_field(
        update,
        name="setActionCooldown",
        number=7,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.SetActionCooldown",
    )
    _add_field(
        update,
        name="setMoveCooldown",
        number=8,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.SetMoveCooldown",
    )
    _add_field(update, name="botOutput", number=9, field_type=TYPE_MESSAGE, type_name=".battlecode.BotOutput")
    _add_field(
        update,
        name="indicatorLine",
        number=10,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.IndicatorLine",
    )
    _add_field(
        update,
        name="indicatorDot",
        number=11,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.IndicatorDot",
    )
    _add_field(update, name="fireTurret", number=12, field_type=TYPE_MESSAGE, type_name=".battlecode.FireTurret")
    _add_field(
        update,
        name="builderAttack",
        number=13,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.BuilderAttack",
    )

    place_entity = _add_message(file_proto, "PlaceEntity")
    _add_field(place_entity, name="entity", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.Entity")

    move_builder_bot = _add_message(file_proto, "MoveBuilderBot")
    _add_field(move_builder_bot, name="id", number=1, field_type=TYPE_INT32)
    _add_field(move_builder_bot, name="to", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")

    remove_entity = _add_message(file_proto, "RemoveEntity")
    _add_field(remove_entity, name="id", number=1, field_type=TYPE_INT32)

    distribute_resources = _add_message(file_proto, "DistributeResources")
    _add_field(
        distribute_resources,
        name="moves",
        number=1,
        field_type=TYPE_MESSAGE,
        label=LABEL_REPEATED,
        type_name=".battlecode.ResourceMove",
    )

    resource_move = _add_message(file_proto, "ResourceMove")
    _add_field(resource_move, name="from", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(resource_move, name="to", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(resource_move, name="resourceId", number=3, field_type=TYPE_INT32, proto3_optional=True)

    update_hp = _add_message(file_proto, "UpdateHp")
    _add_field(update_hp, name="id", number=1, field_type=TYPE_INT32)
    _add_field(update_hp, name="delta", number=2, field_type=TYPE_INT32)

    update_players = _add_message(file_proto, "UpdatePlayers")
    _add_field(
        update_players,
        name="players",
        number=1,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.Players",
    )

    set_action_cooldown = _add_message(file_proto, "SetActionCooldown")
    _add_field(set_action_cooldown, name="id", number=1, field_type=TYPE_INT32)
    _add_field(set_action_cooldown, name="value", number=2, field_type=TYPE_INT32)

    set_move_cooldown = _add_message(file_proto, "SetMoveCooldown")
    _add_field(set_move_cooldown, name="id", number=1, field_type=TYPE_INT32)
    _add_field(set_move_cooldown, name="value", number=2, field_type=TYPE_INT32)

    bot_output = _add_message(file_proto, "BotOutput")
    _add_field(bot_output, name="id", number=1, field_type=TYPE_INT32)
    _add_field(bot_output, name="stdout", number=2, field_type=TYPE_STRING)
    _add_field(bot_output, name="execTimeUs", number=3, field_type=TYPE_UINT32)
    _add_field(bot_output, name="tled", number=4, field_type=TYPE_BOOL)

    indicator_line = _add_message(file_proto, "IndicatorLine")
    _add_field(indicator_line, name="id", number=1, field_type=TYPE_INT32)
    _add_field(indicator_line, name="posA", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(indicator_line, name="posB", number=3, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(indicator_line, name="r", number=4, field_type=TYPE_INT32)
    _add_field(indicator_line, name="g", number=5, field_type=TYPE_INT32)
    _add_field(indicator_line, name="b", number=6, field_type=TYPE_INT32)

    indicator_dot = _add_message(file_proto, "IndicatorDot")
    _add_field(indicator_dot, name="id", number=1, field_type=TYPE_INT32)
    _add_field(indicator_dot, name="pos", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(indicator_dot, name="r", number=3, field_type=TYPE_INT32)
    _add_field(indicator_dot, name="g", number=4, field_type=TYPE_INT32)
    _add_field(indicator_dot, name="b", number=5, field_type=TYPE_INT32)

    builder_attack = _add_message(file_proto, "BuilderAttack")
    _add_field(builder_attack, name="id", number=1, field_type=TYPE_INT32)

    fire_turret = _add_message(file_proto, "FireTurret")
    _add_field(fire_turret, name="from", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(fire_turret, name="to", number=2, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")

    pos = _add_message(file_proto, "Pos")
    _add_field(pos, name="x", number=1, field_type=TYPE_INT32)
    _add_field(pos, name="y", number=2, field_type=TYPE_INT32)

    core_position = _add_message(file_proto, "CorePosition")
    _add_field(core_position, name="id", number=1, field_type=TYPE_INT32)
    _add_field(core_position, name="team", number=2, field_type=TYPE_ENUM, type_name=".battlecode.Team")
    _add_field(core_position, name="position", number=3, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")

    entity = _add_message(file_proto, "Entity")
    _add_field(entity, name="id", number=1, field_type=TYPE_INT32)
    _add_field(entity, name="team", number=2, field_type=TYPE_ENUM, type_name=".battlecode.Team")
    _add_field(entity, name="position", number=3, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(entity, name="hp", number=4, field_type=TYPE_INT32)
    _add_field(entity, name="maxHp", number=5, field_type=TYPE_INT32)
    _add_field(entity, name="builderBot", number=10, field_type=TYPE_MESSAGE, type_name=".battlecode.BuilderBot")
    _add_field(entity, name="conveyor", number=11, field_type=TYPE_MESSAGE, type_name=".battlecode.Conveyor")
    _add_field(entity, name="splitter", number=12, field_type=TYPE_MESSAGE, type_name=".battlecode.Splitter")
    _add_field(
        entity,
        name="armouredConveyor",
        number=13,
        field_type=TYPE_MESSAGE,
        type_name=".battlecode.ArmouredConveyor",
    )
    _add_field(entity, name="bridge", number=14, field_type=TYPE_MESSAGE, type_name=".battlecode.Bridge")
    _add_field(entity, name="harvester", number=15, field_type=TYPE_MESSAGE, type_name=".battlecode.Harvester")
    _add_field(entity, name="foundry", number=16, field_type=TYPE_MESSAGE, type_name=".battlecode.Foundry")
    _add_field(entity, name="road", number=17, field_type=TYPE_MESSAGE, type_name=".battlecode.Road")
    _add_field(entity, name="barrier", number=18, field_type=TYPE_MESSAGE, type_name=".battlecode.Barrier")
    _add_field(entity, name="marker", number=19, field_type=TYPE_MESSAGE, type_name=".battlecode.Marker")
    _add_field(entity, name="core", number=20, field_type=TYPE_MESSAGE, type_name=".battlecode.Core")
    _add_field(entity, name="gunner", number=21, field_type=TYPE_MESSAGE, type_name=".battlecode.Gunner")
    _add_field(entity, name="sentinel", number=22, field_type=TYPE_MESSAGE, type_name=".battlecode.Sentinel")
    _add_field(entity, name="breach", number=23, field_type=TYPE_MESSAGE, type_name=".battlecode.Breach")
    _add_field(entity, name="launcher", number=24, field_type=TYPE_MESSAGE, type_name=".battlecode.Launcher")

    builder_bot = _add_message(file_proto, "BuilderBot")
    _add_field(builder_bot, name="actionCooldown", number=1, field_type=TYPE_INT32)
    _add_field(builder_bot, name="moveCooldown", number=2, field_type=TYPE_INT32)

    conveyor = _add_message(file_proto, "Conveyor")
    _add_field(conveyor, name="direction", number=1, field_type=TYPE_ENUM, type_name=".battlecode.Direction")
    _add_field(conveyor, name="stored", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")

    splitter = _add_message(file_proto, "Splitter")
    _add_field(splitter, name="direction", number=1, field_type=TYPE_ENUM, type_name=".battlecode.Direction")
    _add_field(splitter, name="stored", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")

    armoured_conveyor = _add_message(file_proto, "ArmouredConveyor")
    _add_field(armoured_conveyor, name="direction", number=1, field_type=TYPE_ENUM, type_name=".battlecode.Direction")
    _add_field(armoured_conveyor, name="stored", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")

    bridge = _add_message(file_proto, "Bridge")
    _add_field(bridge, name="target", number=1, field_type=TYPE_MESSAGE, type_name=".battlecode.Pos")
    _add_field(bridge, name="stored", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")

    harvester = _add_message(file_proto, "Harvester")
    _add_field(harvester, name="cooldown", number=1, field_type=TYPE_INT32)
    _add_field(harvester, name="resourceType", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")

    foundry = _add_message(file_proto, "Foundry")
    _add_field(foundry, name="stored", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")

    _add_message(file_proto, "Road")
    _add_message(file_proto, "Barrier")

    marker = _add_message(file_proto, "Marker")
    _add_field(marker, name="value", number=1, field_type=TYPE_UINT32)

    core = _add_message(file_proto, "Core")
    _add_field(core, name="actionCooldown", number=1, field_type=TYPE_INT32)

    gunner = _add_message(file_proto, "Gunner")
    _add_field(gunner, name="direction", number=1, field_type=TYPE_ENUM, type_name=".battlecode.Direction")
    _add_field(gunner, name="ammoType", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")
    _add_field(gunner, name="ammoAmount", number=3, field_type=TYPE_INT32)

    sentinel = _add_message(file_proto, "Sentinel")
    _add_field(sentinel, name="direction", number=1, field_type=TYPE_ENUM, type_name=".battlecode.Direction")
    _add_field(sentinel, name="ammoType", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")
    _add_field(sentinel, name="ammoAmount", number=3, field_type=TYPE_INT32)

    breach = _add_message(file_proto, "Breach")
    _add_field(breach, name="direction", number=1, field_type=TYPE_ENUM, type_name=".battlecode.Direction")
    _add_field(breach, name="ammoType", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")
    _add_field(breach, name="ammoAmount", number=3, field_type=TYPE_INT32)

    launcher = _add_message(file_proto, "Launcher")
    _add_field(launcher, name="ammoType", number=2, field_type=TYPE_ENUM, type_name=".battlecode.ResourceType")
    _add_field(launcher, name="ammoAmount", number=3, field_type=TYPE_INT32)

    return file_proto


@lru_cache(maxsize=1)
def descriptor_pool_for_replays() -> descriptor_pool.DescriptorPool:
    pool = descriptor_pool.DescriptorPool()
    pool.Add(_build_file_descriptor())
    return pool


@lru_cache(maxsize=1)
def replay_message_class():
    descriptor = descriptor_pool_for_replays().FindMessageTypeByName("battlecode.Replay")
    return message_factory.GetMessageClass(descriptor)


@lru_cache(maxsize=1)
def map_message_class():
    descriptor = descriptor_pool_for_replays().FindMessageTypeByName("battlecode.Map")
    return message_factory.GetMessageClass(descriptor)
