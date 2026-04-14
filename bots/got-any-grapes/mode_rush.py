from __future__ import annotations

from cambc import Controller, Direction, EntityType, Position

import navigation
import utils
from states import BuilderMode


HIJACKABLE_PIPELINE_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}
for _name in ("SPLITTER", "BRIDGE"):
    _entity = getattr(EntityType, _name, None)
    if _entity is not None:
        HIJACKABLE_PIPELINE_BUILDINGS.add(_entity)

BUILD_STANCE_BUILDINGS = {
    None,
    EntityType.MARKER,
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}
for _name in ("SPLITTER", "BRIDGE"):
    _entity = getattr(EntityType, _name, None)
    if _entity is not None:
        BUILD_STANCE_BUILDINGS.add(_entity)

TURRET_SITE_BUILDINGS = {
    None,
    EntityType.MARKER,
}

RUSH_TURRET_TYPES = [EntityType.GUNNER, EntityType.SENTINEL]


def _has_rush_plan(bot) -> bool:
    return (
        getattr(bot, "rush_turret_pos", None) is not None
        and getattr(bot, "rush_build_stance", None) is not None
        and getattr(bot, "rush_turret_type", None) is not None
        and getattr(bot, "rush_turret_direction", None) is not None
    )


def _clear_rush_state(bot) -> None:
    bot.rush_target_core_pos = None
    bot.rush_turret_pos = None
    bot.rush_build_stance = None
    bot.rush_turret_type = None
    bot.rush_turret_direction = None
    bot.rush_symmetry_candidates = None
    bot.rush_failed_candidates = set()
    bot.rush_turret_built = False


def _is_visible_current_round(bot, pos: Position, current_round: int) -> bool:
    pos_key = (pos.x, pos.y)
    if pos_key not in getattr(bot, "visible_positions", set()):
        return False
    tile_data = bot.grid.get(pos_key, {})
    return tile_data.get("last_seen") == current_round


def _enemy_core_candidates(bot, ct: Controller) -> list[Position]:
    if getattr(bot, "rush_symmetry_candidates", None) is not None:
        return bot.rush_symmetry_candidates

    core_pos = (
        bot.core_pos
        if getattr(bot, "core_pos", None) is not None
        else ct.get_position()
    )
    width = ct.get_map_width()
    height = ct.get_map_height()
    candidates: list[Position] = []
    seen: set[tuple[int, int]] = set()

    for pos in (
        Position(width - 1 - core_pos.x, height - 1 - core_pos.y),
        Position(width - 1 - core_pos.x, core_pos.y),
        Position(core_pos.x, height - 1 - core_pos.y),
    ):
        key = (pos.x, pos.y)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(pos)

    current_pos = ct.get_position()
    candidates.sort(key=lambda p: current_pos.distance_squared(p))
    bot.rush_symmetry_candidates = candidates
    return candidates


def _visible_enemy_core_pos(ct: Controller) -> Position | None:
    my_team = ct.get_team()
    for unit_id in ct.get_nearby_units():
        if ct.get_entity_type(unit_id) != EntityType.CORE:
            continue
        if ct.get_team(unit_id) == my_team:
            continue
        return ct.get_position(unit_id)
    return None


def _candidate_is_clearly_wrong(bot, ct: Controller, candidate: Position) -> bool:
    if not ct.is_in_vision(candidate):
        return False
    return _visible_enemy_core_pos(ct) is None


def _refresh_target_core(bot, ct: Controller) -> Position | None:
    visible_enemy_core = _visible_enemy_core_pos(ct)
    if visible_enemy_core is not None:
        bot.rush_target_core_pos = visible_enemy_core
        return visible_enemy_core

    failed = getattr(bot, "rush_failed_candidates", set())
    for candidate in _enemy_core_candidates(bot, ct):
        key = (candidate.x, candidate.y)
        if key in failed:
            continue
        if _candidate_is_clearly_wrong(bot, ct, candidate):
            failed.add(key)
            continue
        bot.rush_failed_candidates = failed
        bot.rush_target_core_pos = candidate
        return candidate

    return None


def _all_directions() -> list[Direction]:
    return [
        direction
        for direction in (
            Direction.NORTH,
            Direction.NORTHEAST,
            Direction.EAST,
            Direction.SOUTHEAST,
            Direction.SOUTH,
            Direction.SOUTHWEST,
            Direction.WEST,
            Direction.NORTHWEST,
        )
        if direction is not None
    ]


def _adjacent_positions(pos: Position) -> list[Position]:
    out: list[Position] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            out.append(Position(pos.x + dx, pos.y + dy))
    return out


def _tile_is_build_stance(
    bot,
    ct: Controller,
    pos: Position,
    current_round: int,
) -> bool:
    if not utils.in_bounds(ct, pos):
        return False
    if not _is_visible_current_round(bot, pos, current_round):
        return False

    current_pos = ct.get_position()
    tile_data = bot.grid.get((pos.x, pos.y), {})
    entity_type = tile_data.get("entity")
    if entity_type is not None and pos != current_pos:
        return False

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")
    if building_type == EntityType.CORE:
        return building_team == ct.get_team()
    return building_type in BUILD_STANCE_BUILDINGS


def _tile_is_open_turret_site(
    bot,
    ct: Controller,
    pos: Position,
    current_round: int,
) -> bool:
    if not utils.in_bounds(ct, pos):
        return False
    if not _is_visible_current_round(bot, pos, current_round):
        return False

    tile_data = bot.grid.get((pos.x, pos.y), {})
    if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
        return False
    if tile_data.get("entity") is not None:
        return False
    return tile_data.get("building") in TURRET_SITE_BUILDINGS


def _turret_supply_class(bot, ct: Controller, pos: Position) -> int:
    my_team = ct.get_team()
    connected = getattr(bot, "connected_friendly_conveyors", {}) or {}
    best = 99

    for direction in utils.CARDINAL_DIRECTIONS:
        neighbor = pos.add(direction)
        tile_data = bot.grid.get((neighbor.x, neighbor.y), {})
        building = tile_data.get("building")
        team = tile_data.get("building_team")
        if building == EntityType.HARVESTER:
            if team is not None and team != my_team:
                best = min(best, 0)
            elif team == my_team:
                best = min(best, 1)
            continue
        if (
            building in HIJACKABLE_PIPELINE_BUILDINGS
            and team is not None
            and _transport_feeds_position(tile_data, neighbor, pos)
        ):
            if team != my_team:
                best = min(best, 0)
            elif (neighbor.x, neighbor.y) in connected:
                best = min(best, 2)

    return best


def _transport_feeds_position(data: dict, source_pos: Position, target_pos: Position) -> bool:
    building = data.get("building")
    if building in {EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR}:
        build_dir = data.get("building_dir")
        if build_dir is None:
            return False
        next_pos = source_pos.add(build_dir)
    elif building == EntityType.BRIDGE:
        next_pos = data.get("bridge_target")
        if next_pos is None:
            return False
    else:
        return False
    return next_pos == target_pos


def _transport_points_toward_core(data: dict, source_pos: Position, core_pos: Position) -> bool:
    building = data.get("building")
    if building in {EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR}:
        build_dir = data.get("building_dir")
        if build_dir is None:
            return False
        next_pos = source_pos.add(build_dir)
    elif building == EntityType.BRIDGE:
        next_pos = data.get("bridge_target")
        if next_pos is None:
            return False
    else:
        return False
    return next_pos.distance_squared(core_pos) < source_pos.distance_squared(core_pos)


def _try_clear_enemy_core_logistics_underfoot(bot, ct: Controller, core_pos: Position) -> bool:
    current_pos = ct.get_position()
    data = bot.grid.get((current_pos.x, current_pos.y))
    if not data:
        return False
    if data.get("building") not in HIJACKABLE_PIPELINE_BUILDINGS:
        return False
    team = data.get("building_team")
    if team is None or team == ct.get_team():
        return False
    if not _transport_points_toward_core(data, current_pos, core_pos):
        return False
    if not ct.can_fire(current_pos):
        return False
    ct.fire(current_pos)
    if utils.DEBUG:
        bot.logger.log(f"RUSH: clearing enemy core logistics underfoot at {current_pos}")
    return True


def _harvester_outlets(harvester_pos: Position) -> list[Position]:
    return [
        Position(harvester_pos.x + 1, harvester_pos.y),
        Position(harvester_pos.x - 1, harvester_pos.y),
        Position(harvester_pos.x, harvester_pos.y + 1),
        Position(harvester_pos.x, harvester_pos.y - 1),
    ]


def _choose_turret_plan(ct: Controller, turret_pos: Position, core_pos: Position):
    for turret_type in RUSH_TURRET_TYPES:
        for direction in _all_directions():
            if ct.can_fire_from(turret_pos, direction, turret_type, core_pos):
                return turret_type, direction
    return None


def _best_build_stance(
    bot,
    ct: Controller,
    turret_pos: Position,
    core_pos: Position,
    current_round: int,
) -> Position | None:
    current_pos = ct.get_position()
    stances = [
        pos
        for pos in _adjacent_positions(turret_pos)
        if _tile_is_build_stance(bot, ct, pos, current_round)
    ]
    if not stances:
        return None
    return min(
        stances,
        key=lambda pos: (
            current_pos.distance_squared(pos),
            pos.distance_squared(core_pos),
            pos.x,
            pos.y,
        ),
    )


def _find_visible_core_plan(bot, ct: Controller, core_pos: Position):
    current_round = ct.get_current_round()
    current_pos = ct.get_position()
    candidates = []

    for pos_key in getattr(bot, "visible_positions", set()):
        turret_pos = Position(pos_key[0], pos_key[1])
        if not _tile_is_open_turret_site(bot, ct, turret_pos, current_round):
            continue
        turret_plan = _choose_turret_plan(ct, turret_pos, core_pos)
        if turret_plan is None:
            continue
        supply_class = _turret_supply_class(bot, ct, turret_pos)
        if supply_class >= 99:
            continue
        build_stance = _best_build_stance(
            bot,
            ct,
            turret_pos,
            core_pos,
            current_round,
        )
        if build_stance is None:
            continue
        turret_type, turret_direction = turret_plan
        candidates.append(
            (
                (
                    supply_class,
                    current_pos.distance_squared(build_stance),
                    turret_pos.distance_squared(core_pos),
                    build_stance.x,
                    build_stance.y,
                    turret_pos.x,
                    turret_pos.y,
                ),
                turret_pos,
                build_stance,
                turret_type,
                turret_direction,
            )
        )

    if not candidates:
        return None
    _, turret_pos, build_stance, turret_type, turret_direction = min(
        candidates,
        key=lambda item: item[0],
    )
    return turret_pos, build_stance, turret_type, turret_direction


def _find_visible_hijack_plan(bot, ct: Controller, core_pos: Position):
    current_round = ct.get_current_round()
    my_team = ct.get_team()
    current_pos = ct.get_position()
    candidates = []

    for pos_key in getattr(bot, "visible_positions", set()):
        tile_data = bot.grid.get(pos_key, {})
        if tile_data.get("last_seen") != current_round:
            continue
        if tile_data.get("building") != EntityType.HARVESTER:
            continue
        if tile_data.get("building_team") in {None, my_team}:
            continue

        harvester_pos = Position(pos_key[0], pos_key[1])
        for turret_pos in _harvester_outlets(harvester_pos):
            if not _tile_is_open_turret_site(bot, ct, turret_pos, current_round):
                continue
            turret_plan = _choose_turret_plan(ct, turret_pos, core_pos)
            if turret_plan is None:
                continue
            build_stance = _best_build_stance(
                bot,
                ct,
                turret_pos,
                core_pos,
                current_round,
            )
            if build_stance is None:
                continue
            turret_type, turret_direction = turret_plan
            candidates.append(
                (
                    (
                        harvester_pos.distance_squared(core_pos),
                        turret_pos.distance_squared(core_pos),
                        current_pos.distance_squared(build_stance),
                        current_pos.distance_squared(turret_pos),
                        harvester_pos.x,
                        harvester_pos.y,
                        turret_pos.x,
                        turret_pos.y,
                    ),
                    turret_pos,
                    build_stance,
                    turret_type,
                    turret_direction,
                )
            )

    if not candidates:
        return None
    _, turret_pos, build_stance, turret_type, turret_direction = min(
        candidates,
        key=lambda item: item[0],
    )
    return turret_pos, build_stance, turret_type, turret_direction


def _refresh_rush_plan(bot, ct: Controller, core_pos: Position) -> bool:
    plan = None
    if _visible_enemy_core_pos(ct) is not None:
        plan = _find_visible_core_plan(bot, ct, core_pos)
    if plan is None:
        plan = _find_visible_hijack_plan(bot, ct, core_pos)
    if plan is None:
        return False

    bot.rush_turret_pos = plan[0]
    bot.rush_build_stance = plan[1]
    bot.rush_turret_type = plan[2]
    bot.rush_turret_direction = plan[3]
    return True


def _plan_is_still_usable(bot, ct: Controller, core_pos: Position) -> bool:
    turret_pos = getattr(bot, "rush_turret_pos", None)
    build_stance = getattr(bot, "rush_build_stance", None)
    turret_type = getattr(bot, "rush_turret_type", None)
    turret_direction = getattr(bot, "rush_turret_direction", None)
    if None in {turret_pos, build_stance, turret_type, turret_direction}:
        return False

    current_round = ct.get_current_round()
    if not _tile_is_open_turret_site(bot, ct, turret_pos, current_round):
        return False
    if not _tile_is_build_stance(bot, ct, build_stance, current_round):
        return False
    return ct.can_fire_from(turret_pos, turret_direction, turret_type, core_pos)


def get_rush_spawn_pos(ct: Controller, core_pos: Position) -> Position:
    rotation_guess = Position(
        ct.get_map_width() - 1 - core_pos.x,
        ct.get_map_height() - 1 - core_pos.y,
    )
    candidates = [
        Position(core_pos.x + dx, core_pos.y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    ]
    return min(candidates, key=lambda pos: (pos.distance_squared(rotation_guess), pos.x, pos.y))


def _can_build_turret(
    ct: Controller,
    turret_type: EntityType,
    pos: Position,
    direction: Direction,
) -> bool:
    if turret_type == EntityType.GUNNER:
        return ct.can_build_gunner(pos, direction)
    if turret_type == EntityType.SENTINEL:
        return ct.can_build_sentinel(pos, direction)
    return False


def _build_turret(
    ct: Controller,
    turret_type: EntityType,
    pos: Position,
    direction: Direction,
) -> None:
    if turret_type == EntityType.GUNNER:
        ct.build_gunner(pos, direction)
        return
    if turret_type == EntityType.SENTINEL:
        ct.build_sentinel(pos, direction)
        return
    raise ValueError(f"Unsupported rush turret type: {turret_type}")


def _stop_rushing(bot) -> None:
    if hasattr(bot, "stop_rushing"):
        bot.stop_rushing(fallback=BuilderMode.ASSAULTING)
        return
    _clear_rush_state(bot)
    bot.builder_mode = BuilderMode.ASSAULTING


def _move_towards(bot, ct: Controller, pos: Position, label: str) -> None:
    if utils.DEBUG:
        bot.logger.log(f"RUSH: {label} -> {pos}")
    navigation.move_towards(bot, ct, pos)


def execute(bot, ct: Controller) -> None:
    current_pos = ct.get_position()

    previous_core_pos = getattr(bot, "rush_target_core_pos", None)
    core_pos = _refresh_target_core(bot, ct)
    if core_pos is None:
        if utils.DEBUG:
            bot.logger.log("RUSH: no symmetry candidates left; falling back")
        _stop_rushing(bot)
        return

    core_changed = previous_core_pos != core_pos
    bot.rush_target_core_pos = core_pos

    if _try_clear_enemy_core_logistics_underfoot(bot, ct, core_pos):
        return

    need_refresh = (
        core_changed
        or not _has_rush_plan(bot)
        or not _plan_is_still_usable(bot, ct, core_pos)
    )

    if need_refresh and _refresh_rush_plan(bot, ct, core_pos):
        if utils.DEBUG:
            bot.logger.log(f"RUSH: refreshed sentinel plan for core {core_pos}")

    turret_pos = getattr(bot, "rush_turret_pos", None)
    build_stance = getattr(bot, "rush_build_stance", None)
    turret_type = getattr(bot, "rush_turret_type", None)
    turret_direction = getattr(bot, "rush_turret_direction", None)

    if (
        turret_pos is None
        or build_stance is None
        or turret_type is None
        or turret_direction is None
    ):
        _move_towards(bot, ct, core_pos, "seeking enemy core")
        return

    if current_pos != build_stance:
        _move_towards(bot, ct, build_stance, "taking core-fire stance")
        return

    if _can_build_turret(ct, turret_type, turret_pos, turret_direction):
        _build_turret(ct, turret_type, turret_pos, turret_direction)
        bot.rush_turret_built = True
        if utils.DEBUG:
            bot.logger.log(
                f"RUSH: built {turret_type.name} at {turret_pos} "
                f"facing {turret_direction.name}"
            )
        _stop_rushing(bot)
        return

    if _refresh_rush_plan(bot, ct, core_pos):
        if utils.DEBUG:
            bot.logger.log("RUSH: rebuilt blocked plan at stance")
        return

    if utils.DEBUG:
        bot.logger.log(f"RUSH: holding build stance at {build_stance}")
