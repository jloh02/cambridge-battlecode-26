from cambc import Controller, Direction, EntityType, Position
from states import BuilderMode
import navigation
import utils


# Enemy logistics tiles we are willing to hijack and later replace with a turret.
HIJACKABLE_PIPELINE_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}
for _name in ("SPLITTER", "BRIDGE"):
    _entity = getattr(EntityType, _name, None)
    if _entity is not None:
        HIJACKABLE_PIPELINE_BUILDINGS.add(_entity)

# Tiles the builder can realistically stand on while building the hijacked turret.
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

# We only use sentinels since they have the longest range.
# This gives our rush bot the most options.
# If the enemy is prepared, changing the gun type won't help anyway...
RUSH_TURRET_TYPES = [
    EntityType.SENTINEL
]
RUSH_TURRET_TYPES = [t for t in RUSH_TURRET_TYPES if t is not None]

# Temporary repo-local marker value suggestion for assigning the first spawned builder.
RUSH_ASSIGNMENT_MARKER = 0x52555348  # "RUSH"

def _has_rush_plan(bot) -> bool:
    return (
        getattr(bot, "rush_hijack_pos", None) is not None
        and getattr(bot, "rush_build_stance", None) is not None
        and getattr(bot, "rush_turret_type", None) is not None
        and getattr(bot, "rush_turret_direction", None) is not None
    )

def _harvester_outlets(harvester_pos: Position) -> list[Position]:
    return [
        Position(harvester_pos.x + 1, harvester_pos.y),
        Position(harvester_pos.x - 1, harvester_pos.y),
        Position(harvester_pos.x, harvester_pos.y + 1),
        Position(harvester_pos.x, harvester_pos.y - 1),
    ]


def _tile_is_open_outlet(bot, ct: Controller, pos: Position, current_round: int) -> bool:
    if not utils.in_bounds(ct, pos):
        return False
    if not _is_visible_current_round(bot, pos, current_round):
        return False

    tile_data = bot.grid.get((pos.x, pos.y), {})

    if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
        return False

    # Outlet must be genuinely unoccupied.
    if tile_data.get("entity") is not None:
        return False

    building_type = tile_data.get("building")

    # Keep this conservative. We only treat empty / marker outlets as valid
    # direct build sites. If you know roads are safe to overwrite in your bot
    # line, you can add EntityType.ROAD here too.
    return building_type in {None, EntityType.MARKER}

def _clear_rush_state(bot):
    bot.rush_target_core_pos = None
    bot.rush_hijack_pos = None
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

    core_pos = bot.core_pos if getattr(bot, "core_pos", None) is not None else ct.get_position()
    width = ct.get_map_width()
    height = ct.get_map_height()

    candidates: list[Position] = []
    seen: set[tuple[int, int]] = set()

    for pos in (
        Position(width - 1 - core_pos.x, height - 1 - core_pos.y),   # rotation
        Position(width - 1 - core_pos.x, core_pos.y),                # vertical reflection
        Position(core_pos.x, height - 1 - core_pos.y),               # horizontal reflection
    ):
        key = (pos.x, pos.y)
        if key not in seen:
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
    # If the supposed core centre is in vision and no enemy core unit is visible,
    # that symmetry guess is dead.
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
    directions: list[Direction] = []
    for name in (
        "NORTH",
        "NORTHEAST",
        "EAST",
        "SOUTHEAST",
        "SOUTH",
        "SOUTHWEST",
        "WEST",
        "NORTHWEST",
    ):
        direction = getattr(Direction, name, None)
        if direction is not None:
            directions.append(direction)
    return directions


def _adjacent_positions(pos: Position) -> list[Position]:
    out: list[Position] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            out.append(Position(pos.x + dx, pos.y + dy))
    return out


def _tile_is_build_stance(bot, ct: Controller, pos: Position, current_round: int) -> bool:
    if not utils.in_bounds(ct, pos):
        return False
    if not _is_visible_current_round(bot, pos, current_round):
        return False

    current_pos = ct.get_position()
    tile_data = bot.grid.get((pos.x, pos.y), {})
    entity_type = tile_data.get("entity")
    if entity_type is not None and (pos.x != current_pos.x or pos.y != current_pos.y):
        return False

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")

    if building_type == EntityType.CORE:
        return building_team == ct.get_team()

    return building_type in BUILD_STANCE_BUILDINGS


def _choose_turret_plan(ct: Controller, hijack_pos: Position, core_pos: Position):
    for turret_type in RUSH_TURRET_TYPES:
        for direction in _all_directions():
            if ct.can_fire_from(hijack_pos, direction, turret_type, core_pos):
                return turret_type, direction
    return None

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

        for outlet_pos in _harvester_outlets(harvester_pos):
            if not _tile_is_open_outlet(bot, ct, outlet_pos, current_round):
                continue

            turret_plan = _choose_turret_plan(ct, outlet_pos, core_pos)
            if turret_plan is None:
                continue
            turret_type, turret_direction = turret_plan

            build_stances = [
                p
                for p in _adjacent_positions(outlet_pos)
                if _tile_is_build_stance(bot, ct, p, current_round)
            ]
            if not build_stances:
                continue

            build_stance = min(
                build_stances,
                key=lambda p: (
                    current_pos.distance_squared(p),
                    p.distance_squared(core_pos),
                    p.x,
                    p.y,
                ),
            )

            candidates.append(
                (
                    (
                        harvester_pos.distance_squared(core_pos),
                        outlet_pos.distance_squared(core_pos),
                        current_pos.distance_squared(build_stance),
                        current_pos.distance_squared(outlet_pos),
                        harvester_pos.x,
                        harvester_pos.y,
                        outlet_pos.x,
                        outlet_pos.y,
                    ),
                    outlet_pos,
                    build_stance,
                    turret_type,
                    turret_direction,
                )
            )

    if not candidates:
        return None

    _, hijack_pos, build_stance, turret_type, turret_direction = min(
        candidates, key=lambda item: item[0]
    )
    return hijack_pos, build_stance, turret_type, turret_direction

def _refresh_hijack_plan(bot, ct: Controller, core_pos: Position):
    plan = _find_visible_hijack_plan(bot, ct, core_pos)
    if plan is None:
        return False

    bot.rush_hijack_pos = plan[0]
    bot.rush_build_stance = plan[1]
    bot.rush_turret_type = plan[2]
    bot.rush_turret_direction = plan[3]
    return True


def _enemy_pipeline_still_on_tile(bot, pos: Position) -> bool:
    tile_data = bot.grid.get((pos.x, pos.y), {})
    return tile_data.get("building") in HIJACKABLE_PIPELINE_BUILDINGS and tile_data.get(
        "building_team"
    ) not in {None, tile_data.get("entity_team")}


def _tile_has_enemy_pipeline(bot, ct: Controller, pos: Position, current_round: int) -> bool:
    if not _is_visible_current_round(bot, pos, current_round):
        return False
    tile_data = bot.grid.get((pos.x, pos.y), {})
    return (
        tile_data.get("building") in HIJACKABLE_PIPELINE_BUILDINGS
        and tile_data.get("building_team") not in {None, ct.get_team()}
    )

def _plan_is_still_usable(bot, ct: Controller, core_pos: Position) -> bool:
    hijack_pos = getattr(bot, "rush_hijack_pos", None)
    build_stance = getattr(bot, "rush_build_stance", None)
    turret_type = getattr(bot, "rush_turret_type", None)
    turret_direction = getattr(bot, "rush_turret_direction", None)

    if None in {hijack_pos, build_stance, turret_type, turret_direction}:
        return False

    current_round = ct.get_current_round()

    if not _tile_is_open_outlet(bot, ct, hijack_pos, current_round):
        return False
    if not _tile_is_build_stance(bot, ct, build_stance, current_round):
        return False
    if not ct.can_fire_from(hijack_pos, turret_direction, turret_type, core_pos):
        return False

    return True


def _move_towards(bot, ct: Controller, pos: Position, label: str):
    bot.logger.log(f"RUSH: {label} -> {pos}")
    navigation.move_towards(bot, ct, pos)

def get_rush_spawn_pos(ct: Controller, core_pos: Position) -> Position:
    # Pick the core tile furthest "outward" toward the rotationally symmetric
    # enemy-core guess. This is just a cheap opening tempo gain.
    rotation_guess = Position(
        ct.get_map_width() - 1 - core_pos.x,
        ct.get_map_height() - 1 - core_pos.y,
    )

    candidates = [
        Position(core_pos.x + dx, core_pos.y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    ]
    return min(
        candidates,
        key=lambda p: (
            p.distance_squared(rotation_guess),
            p.x,
            p.y,
        )
    )


def _can_build_turret(
    ct: Controller,
    turret_type: EntityType,
    pos: Position,
    direction: Direction,
) -> bool:
    if turret_type == EntityType.GUNNER:
        return ct.can_build_gunner(pos, direction)

    sentinel = getattr(EntityType, "SENTINEL", None)
    if sentinel is not None and turret_type == sentinel:
        return ct.can_build_sentinel(pos, direction)

    breach = getattr(EntityType, "BREACH", None)
    if breach is not None and turret_type == breach:
        return ct.can_build_breach(pos, direction)

    return False


def _build_turret(
    ct: Controller,
    turret_type: EntityType,
    pos: Position,
    direction: Direction,
):
    if turret_type == EntityType.GUNNER:
        return ct.build_gunner(pos, direction)

    sentinel = getattr(EntityType, "SENTINEL", None)
    if sentinel is not None and turret_type == sentinel:
        return ct.build_sentinel(pos, direction)

    breach = getattr(EntityType, "BREACH", None)
    if breach is not None and turret_type == breach:
        return ct.build_breach(pos, direction)

    raise ValueError(f"Unsupported rush turret type: {turret_type}")

def execute(bot, ct: Controller):
    current_pos = ct.get_position()

    previous_core_pos = getattr(bot, "rush_target_core_pos", None)
    core_pos = _refresh_target_core(bot, ct)
    if core_pos is None:
        bot.logger.log("RUSH: no symmetry candidates left; falling back")
        _clear_rush_state(bot)
        bot.builder_mode = BuilderMode.EXPLORING
        return

    core_changed = previous_core_pos != core_pos
    bot.rush_target_core_pos = core_pos

    need_refresh = (
        core_changed
        or not _has_rush_plan(bot)
        or not _plan_is_still_usable(bot, ct, core_pos)
    )

    if need_refresh:
        refreshed = _refresh_hijack_plan(bot, ct, core_pos)
        if refreshed:
            bot.logger.log(f"RUSH: refreshed plan for core {core_pos}")

    hijack_pos = getattr(bot, "rush_hijack_pos", None)
    build_stance = getattr(bot, "rush_build_stance", None)
    turret_type = getattr(bot, "rush_turret_type", None)
    turret_direction = getattr(bot, "rush_turret_direction", None)

    if (
        hijack_pos is None
        or build_stance is None
        or turret_type is None
        or turret_direction is None
    ):
        _move_towards(bot, ct, core_pos, "seeking enemy core")
        return

    if current_pos != build_stance:
        _move_towards(bot, ct, build_stance, "taking rush build stance")
        return

    if _can_build_turret(ct, turret_type, hijack_pos, turret_direction):
        _build_turret(ct, turret_type, hijack_pos, turret_direction)
        bot.rush_turret_built = True
        bot.logger.log(
            f"RUSH: built {turret_type.name} at {hijack_pos} facing {turret_direction.name}"
        )
        # After this, bot is done and will resume normal builder behavior.
        bot.stop_rushing()
        return

    # Recompute once more if the outlet was occupied or stance changed under us.
    if _refresh_hijack_plan(bot, ct, core_pos):
        bot.logger.log("RUSH: rebuilt plan at build stance")
        return

    bot.logger.log(f"RUSH: holding build stance at {build_stance}")
