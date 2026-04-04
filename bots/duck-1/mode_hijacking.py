from cambc import Controller, EntityType, Position
from states import BuilderMode
import mode_finding_ore
import navigation
import utils


HIJACKABLE_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}
STANDABLE_BUILDINGS = {
    None,
    EntityType.ROAD,
    EntityType.MARKER,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.CORE,
}


def _is_visible_current_round(bot, pos: Position, current_round: int) -> bool:
    pos_key = (pos.x, pos.y)
    if pos_key not in getattr(bot, "visible_positions", set()):
        return False
    tile_data = bot.grid.get(pos_key, {})
    return tile_data.get("last_seen") == current_round


def _tile_supports_hijack_entry(bot, ct: Controller, pos: Position, current_round: int) -> bool:
    if not utils.in_bounds(ct, pos):
        return False
    if not _is_visible_current_round(bot, pos, current_round):
        return False

    tile_data = bot.grid.get((pos.x, pos.y), {})
    if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
        return False

    entity_type = tile_data.get("entity")
    entity_team = tile_data.get("entity_team")
    current_pos = ct.get_position()
    if entity_type is not None and (
        pos.x != current_pos.x or pos.y != current_pos.y
    ):
        return False
    if entity_type == EntityType.BUILDER_BOT and entity_team != ct.get_team():
        return False

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")
    if building_type not in STANDABLE_BUILDINGS:
        return False
    if building_type == EntityType.CORE and building_team != ct.get_team():
        return False
    if (
        building_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
        and building_team != ct.get_team()
    ):
        return False
    return building_team in {None, ct.get_team()}


def _hijack_candidate_key(bot, current_pos: Position, source_pos: Position, entry_pos: Position):
    core_pos = bot.core_pos if bot.core_pos is not None else current_pos
    return (
        current_pos.distance_squared(entry_pos),
        utils.manhattan(entry_pos, core_pos),
        current_pos.distance_squared(source_pos),
        source_pos.x,
        source_pos.y,
    )


def find_visible_hijack_target(bot, ct: Controller) -> tuple[Position, Position] | None:
    current_round = ct.get_current_round()
    current_pos = ct.get_position()
    my_team = ct.get_team()
    best = None
    best_key = None

    for pos_key in getattr(bot, "visible_positions", set()):
        tile_data = bot.grid.get(pos_key, {})
        if tile_data.get("last_seen") != current_round:
            continue
        if tile_data.get("building") not in HIJACKABLE_BUILDINGS:
            continue
        if tile_data.get("building_team") in {None, my_team}:
            continue

        build_dir = tile_data.get("building_dir")
        if build_dir is None:
            continue

        source_pos = Position(pos_key[0], pos_key[1])
        entry_pos = source_pos.add(build_dir)
        if not _tile_supports_hijack_entry(bot, ct, entry_pos, current_round):
            continue

        candidate_key = _hijack_candidate_key(bot, current_pos, source_pos, entry_pos)
        if best_key is None or candidate_key < best_key:
            best_key = candidate_key
            best = (source_pos, entry_pos)

    return best


def _clear_hijack_state(bot):
    bot.hijack_source_pos = None
    bot.hijack_entry_pos = None


def execute(bot, ct: Controller):
    target = find_visible_hijack_target(bot, ct)
    if target is None:
        _clear_hijack_state(bot)
        bot.builder_mode = BuilderMode.EXPLORING
        return

    bot.hijack_source_pos, bot.hijack_entry_pos = target
    current_pos = ct.get_position()
    entry_pos = bot.hijack_entry_pos

    if current_pos != entry_pos:
        bot.logger.log(
            f"Hijacking enemy conveyor at {bot.hijack_source_pos} via {entry_pos}"
        )
        navigation.move_towards(bot, ct, entry_pos)
        return

    bot.logger.log(
        f"Reached hijack entry {entry_pos}; switching to tiling-back toward friendly lane"
    )
    mode_finding_ore.enter_tiling_back_from_origin(
        bot,
        entry_pos,
        origin_kind="HIJACK",
    )
    _clear_hijack_state(bot)
