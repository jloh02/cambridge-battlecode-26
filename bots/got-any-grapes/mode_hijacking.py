from cambc import Controller, Direction, EntityType, GameConstants, Position
from states import BuilderMode
import assault
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

# Open-outlet building kinds we are willing to seal with a barrier. The None
# sentinel here represents "no building at all".
_OPEN_OUTLET_BUILDINGS = frozenset({None, EntityType.MARKER})
HIJACK_SENTINEL_MEMORY_TTL = 80
HIJACK_SENTINEL_MIN_TITANIUM = GameConstants.SENTINEL_BASE_COST[0]
HIJACK_MIN_CONNECTED_TRANSPORTS = 4

HIJACK_SENTINEL_TARGET_PRIORITY = {
    EntityType.BUILDER_BOT: 0,
    EntityType.GUNNER: 1,
    EntityType.SENTINEL: 1,
    EntityType.BREACH: 1,
    EntityType.LAUNCHER: 1,
    EntityType.CORE: 2,
    EntityType.CONVEYOR: 3,
    EntityType.ARMOURED_CONVEYOR: 3,
    EntityType.SPLITTER: 3,
    EntityType.BRIDGE: 3,
    EntityType.FOUNDRY: 3,
    EntityType.HARVESTER: 4,
}


def economy_ready_for_hijack(bot, ct: Controller | None = None) -> bool:
    """Only peel economy builders after local evidence of a supplied Ti lane.

    `connected_friendly_conveyors` membership alone is not enough: a core-adjacent
    stub or stale repair fragment can reach the core without proving that a
    harvester is feeding it. The load values are produced from locally tracked
    friendly harvesters, so a positive value is the cheap private-state proof
    that at least one visible source reaches the core.
    """
    connected = getattr(bot, "connected_friendly_conveyors", None) or {}
    if len(connected) < HIJACK_MIN_CONNECTED_TRANSPORTS:
        return False

    has_source_load = False
    for load in connected.values():
        try:
            if int(load) > 0:
                has_source_load = True
                break
        except (TypeError, ValueError):
            continue
    if not has_source_load:
        return False

    if ct is None:
        return True
    get_resources = getattr(ct, "get_global_resources", None)
    if not callable(get_resources):
        return True
    try:
        titanium, _axionite = get_resources()
    except Exception:
        return True
    return titanium >= HIJACK_SENTINEL_MIN_TITANIUM


def _is_visible_current_round(bot, pos: Position, current_round: int) -> bool:
    pos_key = (pos.x, pos.y)
    if pos_key not in getattr(bot, "visible_positions", set()):
        return False
    tile_data = bot.grid.get(pos_key)
    if tile_data is None:
        return False
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

    tile_data = bot.grid.get((pos.x, pos.y))
    if tile_data is None:
        return False
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
    tx, ty = target_pos.x, target_pos.y

    grid_get = bot.grid.get
    builder_bot_kind = EntityType.BUILDER_BOT
    for pos_key in getattr(bot, "visible_positions", None) or ():
        tile_data = grid_get(pos_key)
        if tile_data is None:
            continue
        if tile_data.get("last_seen") != current_round:
            continue
        if tile_data.get("entity") is not builder_bot_kind:
            continue
        if tile_data.get("entity_team") == my_team:
            continue

        dx = pos_key[0] - tx
        dy = pos_key[1] - ty
        if dx * dx + dy * dy <= 2:
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

    tile_data = bot.grid.get((outlet_pos.x, outlet_pos.y))
    if tile_data is None:
        return None
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
    if building_type in _OPEN_OUTLET_BUILDINGS and _tile_supports_hijack_entry(
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

    grid_get = bot.grid.get
    harvester_kind = EntityType.HARVESTER
    for pos_key in getattr(bot, "visible_positions", None) or ():
        tile_data = grid_get(pos_key)
        if tile_data is None:
            continue
        if tile_data.get("last_seen") != current_round:
            continue

        building_type = tile_data.get("building")
        if building_type is not harvester_kind:
            continue
        building_team = tile_data.get("building_team")
        if building_team is None or building_team == my_team:
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
            ox, oy = outlet_pos.x, outlet_pos.y
            seal_reach = sum(
                1
                for other in open_sealable_outlets
                if other is not outlet_pos
                and (ox - other.x) ** 2 + (oy - other.y) ** 2 <= 2
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


def _has_titanium_for_hijack_sentinel(ct: Controller) -> bool:
    get_resources = getattr(ct, "get_global_resources", None)
    if not callable(get_resources):
        return True
    try:
        titanium, _axionite = get_resources()
    except Exception:
        return True
    return titanium >= HIJACK_SENTINEL_MIN_TITANIUM


def _recent_hijack_sentinel_for_harvester(
    bot,
    harvester_pos: Position,
    current_round: int,
) -> bool:
    if getattr(bot, "hijack_sentinel_harvester_pos", None) != harvester_pos:
        return False
    return current_round - getattr(bot, "hijack_sentinel_round", -9999) <= (
        HIJACK_SENTINEL_MEMORY_TTL
    )


def _direction_score_for_hijack_sentinel(
    bot,
    harvester_pos: Position,
    sentinel_pos: Position,
    direction,
) -> tuple[int, int, int, int, int, int, int]:
    attack_tiles = assault.sentinel_attack_tiles(sentinel_pos, direction)
    best_target = (9, 9999, 9999, 9999)
    best_target_pos = None
    for enemy in getattr(bot, "visible_enemy_targets", None) or ():
        enemy_pos = enemy.position
        if enemy_pos == harvester_pos:
            continue
        if (enemy_pos.x, enemy_pos.y) not in attack_tiles:
            continue
        priority = HIJACK_SENTINEL_TARGET_PRIORITY.get(enemy.entity_type, 5)
        target_key = (
            priority,
            sentinel_pos.distance_squared(enemy_pos),
            enemy_pos.x,
            enemy_pos.y,
        )
        if target_key < best_target:
            best_target = target_key
            best_target_pos = enemy_pos

    feed_direction = sentinel_pos.direction_to(harvester_pos)
    away_direction = (
        utils.opposite_direction(feed_direction)
        if feed_direction is not None
        else None
    )
    direct_target_rank = 0
    if best_target_pos is not None:
        target_dx = (best_target_pos.x > sentinel_pos.x) - (
            best_target_pos.x < sentinel_pos.x
        )
        target_dy = (best_target_pos.y > sentinel_pos.y) - (
            best_target_pos.y < sentinel_pos.y
        )
        direct_direction = utils.direction_from_delta(target_dx, target_dy)
        direct_target_rank = (
            0
            if direction == direct_direction
            else 1
        )
    away_rank = 0 if direction == away_direction else 1
    dx, dy = direction.delta()
    return (
        best_target[0],
        best_target[1],
        direct_target_rank,
        away_rank,
        best_target[2],
        best_target[3],
        dx * 10 + dy,
    )


def _hijack_sentinel_direction_candidates(
    bot,
    harvester_pos: Position,
    sentinel_pos: Position,
) -> list[tuple[tuple[int, int, int, int, int, int, int], Direction]]:
    candidates = []
    for direction in utils.DIRECTIONS:
        if not assault.can_feed_sentinel(harvester_pos, sentinel_pos, direction):
            continue
        candidates.append(
            (
                _direction_score_for_hijack_sentinel(
                    bot,
                    harvester_pos,
                    sentinel_pos,
                    direction,
                ),
                direction,
            )
        )
    candidates.sort(key=lambda item: item[0])
    return candidates


def _choose_hijack_sentinel_direction(
    bot,
    harvester_pos: Position,
    sentinel_pos: Position,
):
    candidates = _hijack_sentinel_direction_candidates(
        bot,
        harvester_pos,
        sentinel_pos,
    )
    if not candidates:
        return None
    return candidates[0][1]


def _best_hijack_sentinel_stance(
    bot,
    ct: Controller,
    sentinel_pos: Position,
    current_round: int,
) -> Position | None:
    current_pos = ct.get_position()
    if current_pos != sentinel_pos and current_pos.distance_squared(sentinel_pos) <= 2:
        return current_pos

    candidates = []
    for direction in utils.DIRECTIONS:
        stance = sentinel_pos.add(direction)
        if stance == sentinel_pos:
            continue
        if not _tile_supports_hijack_entry(bot, ct, stance, current_round):
            continue
        candidates.append(
            (
                current_pos.distance_squared(stance),
                stance.x,
                stance.y,
                stance,
            )
        )
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[3]


def _try_build_hijack_sentinel_on_open_outlet(
    bot,
    ct: Controller,
    harvester_pos: Position,
    outlet_pos: Position,
    current_round: int,
) -> bool:
    if not _has_titanium_for_hijack_sentinel(ct):
        return False
    if _recent_hijack_sentinel_for_harvester(bot, harvester_pos, current_round):
        return False
    current_pos = ct.get_position()
    if current_pos == outlet_pos or current_pos.distance_squared(outlet_pos) > 2:
        return False
    if (
        _classify_harvester_outlet(bot, ct, outlet_pos, current_round)
        != "OPEN_SEALABLE"
    ):
        return False
    can_build = getattr(ct, "can_build_sentinel", None)
    build = getattr(ct, "build_sentinel", None)
    if not callable(can_build) or not callable(build):
        return False
    chosen_direction = None
    for _score, direction in _hijack_sentinel_direction_candidates(
        bot,
        harvester_pos,
        outlet_pos,
    ):
        if can_build(outlet_pos, direction):
            chosen_direction = direction
            break
    if chosen_direction is None:
        return False
    build(outlet_pos, chosen_direction)
    bot.hijack_sentinel_pos = outlet_pos
    bot.hijack_sentinel_harvester_pos = harvester_pos
    bot.hijack_sentinel_round = current_round
    if utils.DEBUG:
        bot.logger.log(
            f"Hijack sentinel on enemy harvester outlet {outlet_pos} "
            f"facing {chosen_direction.name}"
        )
    return True


def _try_attack_current_outlet(bot, ct: Controller) -> bool:
    current_pos = ct.get_position()
    tile_data = bot.grid.get((current_pos.x, current_pos.y))
    if tile_data is None:
        return False
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

        tile_data = bot.grid.get((outlet_pos.x, outlet_pos.y))
        if tile_data is None:
            continue
        if tile_data.get("env") in utils.DO_NOT_BUILD_ON:
            continue

        # Only barrier genuinely open sides. Roads/barriers/other buildings already seal.
        if tile_data.get("building") not in _OPEN_OUTLET_BUILDINGS:
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
    if utils.DEBUG:
        bot.logger.log(f"Sealing extra harvester outlet at {outlet_pos}")
    return True


def _hijack_completion_fallback(bot, ct: Controller, secured_pos: Position | None) -> None:
    """Choose the right post-hijack mode based on the bot's role.

    Assault-role bots (including post-turret rushers) stay in enemy territory
    and continue disrupting — they NEVER tile back to our core. Economy
    builders tile back to connect the hijacked harvester to our logistics."""
    _clear_hijack_state(bot)
    if getattr(bot, "is_assault_role", False):
        bot.builder_mode = BuilderMode.ASSAULTING
        if utils.DEBUG:
            bot.logger.log(
                f"assault hijack complete at {secured_pos}; continuing disruption"
            )
        return
    if secured_pos is not None:
        mode_finding_ore.enter_tiling_back_from_origin(
            bot,
            secured_pos,
            origin_kind="HIJACK",
        )
    else:
        bot.builder_mode = BuilderMode.EXPLORING


def execute(bot, ct: Controller):
    target = find_visible_hijack_target(bot, ct)
    if target is None:
        current_pos = ct.get_position()
        remembered_entry = bot.hijack_entry_pos
        if remembered_entry is not None and current_pos == remembered_entry:
            if utils.DEBUG:
                bot.logger.log(
                    f"Hijack target lost at secured outlet {remembered_entry}"
                )
            _hijack_completion_fallback(bot, ct, remembered_entry)
            return
        _hijack_completion_fallback(bot, ct, None)
        return

    bot.hijack_source_pos, bot.hijack_entry_pos = target
    harvester_pos = bot.hijack_source_pos
    entry_pos = bot.hijack_entry_pos
    current_pos = ct.get_position()
    current_round = ct.get_current_round()
    entry_kind = _classify_harvester_outlet(bot, ct, entry_pos, current_round)

    if (
        entry_kind == "OPEN_SEALABLE"
        and _has_titanium_for_hijack_sentinel(ct)
        and not _recent_hijack_sentinel_for_harvester(
            bot,
            harvester_pos,
            current_round,
        )
    ):
        if _try_build_hijack_sentinel_on_open_outlet(
            bot,
            ct,
            harvester_pos,
            entry_pos,
            current_round,
        ):
            return
        stance = _best_hijack_sentinel_stance(bot, ct, entry_pos, current_round)
        if stance is not None and current_pos != stance:
            if utils.DEBUG:
                bot.logger.log(
                    f"Taking hijack sentinel stance {stance} for outlet {entry_pos}"
                )
            navigation.move_towards(bot, ct, stance)
            return

    if current_pos != entry_pos:
        if utils.DEBUG:
            bot.logger.log(
                f"Contesting enemy harvester at {harvester_pos} via outlet {entry_pos}"
            )
        navigation.move_towards(bot, ct, entry_pos)
        return

    # If we are standing on an active enemy conveyor-family outlet, grind it down.
    if _try_attack_current_outlet(bot, ct):
        if utils.DEBUG:
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
        if utils.DEBUG:
            bot.logger.log(
                f"Holding hijack outlet {entry_pos}; {enemy_pressure} enemy builder(s) contesting harvester"
            )
        return

    if utils.DEBUG:
        bot.logger.log(f"Harvester outlet {entry_pos} secured")
    _hijack_completion_fallback(bot, ct, entry_pos)
