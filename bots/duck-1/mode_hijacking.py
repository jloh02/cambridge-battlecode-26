from cambc import Controller, EntityType, Position
from states import BuilderMode
import mode_finding_ore
import navigation
import utils


# Conveyor-family buildings builders can stand on and contest directly.
WALKABLE_CONVEYOR_BUILDINGS = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}
for _name in ("SPLITTER", "BRIDGE"):
    _entity = getattr(EntityType, _name, None)
    if _entity is not None:
        WALKABLE_CONVEYOR_BUILDINGS.add(_entity)

# Buildings that can plausibly be active harvester outlets.
ACCEPTING_HARVESTER_OUTLET_BUILDINGS = set(WALKABLE_CONVEYOR_BUILDINGS)
for _name in ("FOUNDRY", "CORE"):
    _entity = getattr(EntityType, _name, None)
    if _entity is not None:
        ACCEPTING_HARVESTER_OUTLET_BUILDINGS.add(_entity)

# Tiles we are willing to path onto as an outlet-entry / contest tile.
STANDABLE_BUILDINGS = {
    None,
    EntityType.ROAD,
    EntityType.MARKER,
    EntityType.CORE,
}
STANDABLE_BUILDINGS.update(WALKABLE_CONVEYOR_BUILDINGS)


def _is_visible_current_round(bot, pos: Position, current_round: int) -> bool:
    pos_key = (pos.x, pos.y)
    if pos_key not in getattr(bot, "visible_positions", set()):
        return False
    tile_data = bot.grid.get(pos_key, {})
    return tile_data.get("last_seen") == current_round


def _harvester_outlets(harvester_pos: Position) -> list[Position]:
    return [
        Position(harvester_pos.x + 1, harvester_pos.y),
        Position(harvester_pos.x - 1, harvester_pos.y),
        Position(harvester_pos.x, harvester_pos.y + 1),
        Position(harvester_pos.x, harvester_pos.y - 1),
    ]


def _tile_supports_hijack_entry(
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

    # We cannot move onto a tile currently occupied by another visible builder,
    # unless it is our current tile.
    entity_type = tile_data.get("entity")
    current_pos = ct.get_position()
    if entity_type is not None and (pos.x != current_pos.x or pos.y != current_pos.y):
        return False

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")

    if building_type not in STANDABLE_BUILDINGS:
        return False

    # Enemy/allied conveyors are both contestable. Enemy core is not.
    if building_type == EntityType.CORE and building_team != ct.get_team():
        return False

    return True


def _count_visible_enemy_builders_near(
    bot,
    ct: Controller,
    target_pos: Position,
    current_round: int,
) -> int:
    my_team = ct.get_team()
    count = 0

    for pos_key in getattr(bot, "visible_positions", set()):
        tile_data = bot.grid.get(pos_key, {})
        if tile_data.get("last_seen") != current_round:
            continue
        if tile_data.get("entity") != EntityType.BUILDER_BOT:
            continue
        if tile_data.get("entity_team") == my_team:
            continue

        pos = Position(pos_key[0], pos_key[1])
        if target_pos.distance_squared(pos) <= 2:
            count += 1

    return count


def _classify_harvester_outlet(
    bot,
    ct: Controller,
    outlet_pos: Position,
    current_round: int,
) -> str | None:
    if not utils.in_bounds(ct, outlet_pos):
        return None
    if not _is_visible_current_round(bot, outlet_pos, current_round):
        return None

    tile_data = bot.grid.get((outlet_pos.x, outlet_pos.y), {})
    if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
        return None

    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")

    # Best case: enemy conveyor-family outlet we can stand on and attack directly.
    if (
        building_type in WALKABLE_CONVEYOR_BUILDINGS
        and building_team not in {None, ct.get_team()}
        and _tile_supports_hijack_entry(bot, ct, outlet_pos, current_round)
    ):
        return "ACTIVE_WALKABLE_ENEMY"

    # Still an active enemy outlet, but not one we can directly stand on.
    if building_type in ACCEPTING_HARVESTER_OUTLET_BUILDINGS and building_team not in {
        None,
        ct.get_team(),
    }:
        return "ACTIVE_ENEMY"

    # Empty / marker tile: can be stolen or sealed.
    if building_type in {None, EntityType.MARKER} and _tile_supports_hijack_entry(
        bot, ct, outlet_pos, current_round
    ):
        return "OPEN_SEALABLE"

    # Roads / barriers / other non-accepting occupants already block this side.
    return "BLOCKED"


def _core_distance_key(bot, pos: Position) -> int:
    core_pos = bot.core_pos if bot.core_pos is not None else pos
    return utils.manhattan(pos, core_pos)


def _active_candidate_key(
    bot,
    ct: Controller,
    harvester_pos: Position,
    outlet_pos: Position,
    enemy_pressure: int,
    active_outlet_count: int,
    open_outlet_count: int,
):
    current_pos = ct.get_position()
    return (
        -enemy_pressure,                  # contest hot harvesters first
        -active_outlet_count,            # more active enemy outlets -> higher priority
        -open_outlet_count,              # more remaining sides -> better steal payoff
        current_pos.distance_squared(outlet_pos),
        _core_distance_key(bot, outlet_pos),
        harvester_pos.x,
        harvester_pos.y,
        outlet_pos.x,
        outlet_pos.y,
    )


def _seal_candidate_key(
    bot,
    ct: Controller,
    harvester_pos: Position,
    outlet_pos: Position,
    enemy_pressure: int,
    open_outlet_count: int,
    seal_reach: int,
):
    current_pos = ct.get_position()
    return (
        -enemy_pressure,                  # if enemy builders are nearby, contest it now
        -open_outlet_count,               # prefer harvesters with more sides left open
        -seal_reach,                      # from this outlet we can barrier more neighbours
        current_pos.distance_squared(outlet_pos),
        _core_distance_key(bot, outlet_pos),
        harvester_pos.x,
        harvester_pos.y,
        outlet_pos.x,
        outlet_pos.y,
    )


def find_visible_hijack_target(bot, ct: Controller) -> tuple[Position, Position] | None:
    current_round = ct.get_current_round()
    my_team = ct.get_team()

    active_candidates: list[tuple[tuple, Position, Position]] = []
    seal_candidates: list[tuple[tuple, Position, Position]] = []

    for pos_key in getattr(bot, "visible_positions", set()):
        tile_data = bot.grid.get(pos_key, {})
        if tile_data.get("last_seen") != current_round:
            continue
        if tile_data.get("building") != EntityType.HARVESTER:
            continue
        if tile_data.get("building_team") in {None, my_team}:
            continue

        harvester_pos = Position(pos_key[0], pos_key[1])
        enemy_pressure = _count_visible_enemy_builders_near(
            bot, ct, harvester_pos, current_round
        )

        active_walkable_outlets: list[Position] = []
        open_sealable_outlets: list[Position] = []

        for outlet_pos in _harvester_outlets(harvester_pos):
            outlet_kind = _classify_harvester_outlet(
                bot, ct, outlet_pos, current_round
            )
            if outlet_kind == "ACTIVE_WALKABLE_ENEMY":
                active_walkable_outlets.append(outlet_pos)
            elif outlet_kind == "OPEN_SEALABLE":
                open_sealable_outlets.append(outlet_pos)

        # Phase 1: explicitly target active, high-priority enemy outlets first.
        if active_walkable_outlets:
            for outlet_pos in active_walkable_outlets:
                key = _active_candidate_key(
                    bot,
                    ct,
                    harvester_pos,
                    outlet_pos,
                    enemy_pressure,
                    active_outlet_count=len(active_walkable_outlets),
                    open_outlet_count=len(open_sealable_outlets),
                )
                active_candidates.append((key, harvester_pos, outlet_pos))
            continue

        # Phase 2: otherwise go seal / steal the remaining open sides.
        for outlet_pos in open_sealable_outlets:
            seal_reach = sum(
                1
                for other in open_sealable_outlets
                if other != outlet_pos and outlet_pos.distance_squared(other) <= 2
            )
            key = _seal_candidate_key(
                bot,
                ct,
                harvester_pos,
                outlet_pos,
                enemy_pressure,
                open_outlet_count=len(open_sealable_outlets),
                seal_reach=seal_reach,
            )
            seal_candidates.append((key, harvester_pos, outlet_pos))

    if active_candidates:
        _, harvester_pos, outlet_pos = min(active_candidates, key=lambda item: item[0])
        return harvester_pos, outlet_pos

    if seal_candidates:
        _, harvester_pos, outlet_pos = min(seal_candidates, key=lambda item: item[0])
        return harvester_pos, outlet_pos

    return None


def _clear_hijack_state(bot):
    bot.hijack_source_pos = None
    bot.hijack_entry_pos = None


def _try_attack_current_outlet(bot, ct: Controller) -> bool:
    current_pos = ct.get_position()
    tile_data = bot.grid.get((current_pos.x, current_pos.y), {})
    building_type = tile_data.get("building")
    building_team = tile_data.get("building_team")

    if (
        building_type in WALKABLE_CONVEYOR_BUILDINGS
        and building_team not in {None, ct.get_team()}
        and ct.can_fire(current_pos)
    ):
        ct.fire(current_pos)
        return True

    return False


def _try_seal_other_outlets(
    bot,
    ct: Controller,
    harvester_pos: Position,
    current_round: int,
) -> bool:
    current_pos = ct.get_position()
    candidates: list[tuple[tuple[int, int, int], Position]] = []

    for outlet_pos in _harvester_outlets(harvester_pos):
        if outlet_pos == current_pos:
            continue
        if current_pos.distance_squared(outlet_pos) > 2:
            continue
        if not _is_visible_current_round(bot, outlet_pos, current_round):
            continue

        tile_data = bot.grid.get((outlet_pos.x, outlet_pos.y), {})
        if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
            continue

        # Only barrier genuinely open sides. Roads/barriers/other buildings already seal.
        if tile_data.get("building") not in {None, EntityType.MARKER}:
            continue
        if tile_data.get("entity") is not None:
            continue
        if not ct.can_build_barrier(outlet_pos):
            continue

        # Prefer outlets farther from home / more exposed first.
        candidates.append(
            (
                (
                    -_core_distance_key(bot, outlet_pos),
                    harvester_pos.distance_squared(outlet_pos),
                    outlet_pos.x * 1000 + outlet_pos.y,
                ),
                outlet_pos,
            )
        )

    if not candidates:
        return False

    _, outlet_pos = min(candidates, key=lambda item: item[0])
    ct.build_barrier(outlet_pos)
    bot.logger.log(f"Sealing extra harvester outlet at {outlet_pos}")
    return True


def execute(bot, ct: Controller):
    target = find_visible_hijack_target(bot, ct)
    if target is None:
        _clear_hijack_state(bot)
        bot.builder_mode = BuilderMode.EXPLORING
        return

    bot.hijack_source_pos, bot.hijack_entry_pos = target
    harvester_pos = bot.hijack_source_pos
    entry_pos = bot.hijack_entry_pos
    current_pos = ct.get_position()
    current_round = ct.get_current_round()

    if current_pos != entry_pos:
        bot.logger.log(
            f"Contesting enemy harvester at {harvester_pos} via outlet {entry_pos}"
        )
        navigation.move_towards(bot, ct, entry_pos)
        return

    # If we are standing on an active enemy conveyor-family outlet, grind it down.
    if _try_attack_current_outlet(bot, ct):
        bot.logger.log(
            f"Attacking enemy outlet underfoot at {current_pos} for harvester {harvester_pos}"
        )
        return

    # While adjacent, try to barrier off other open sides before backing a lane out.
    if _try_seal_other_outlets(bot, ct, harvester_pos, current_round):
        return

    # Builders cannot directly hit adjacent enemy builders, so when enemy pressure
    # is present we simply hold the outlet tile and deny it.
    enemy_pressure = _count_visible_enemy_builders_near(
        bot, ct, harvester_pos, current_round
    )
    if enemy_pressure > 0:
        bot.logger.log(
            f"Holding hijack outlet {entry_pos}; {enemy_pressure} enemy builder(s) contesting harvester"
        )
        return

    bot.logger.log(
        f"Harvester outlet {entry_pos} secured; switching to tiling-back toward friendly lane"
    )
    mode_finding_ore.enter_tiling_back_from_origin(
        bot,
        entry_pos,
        origin_kind="HIJACK",
    )
    _clear_hijack_state(bot)