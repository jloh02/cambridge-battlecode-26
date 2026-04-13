from cambc import Controller, EntityType, GameConstants, Position
from states import BuilderMode
import utils


CORE_BUILDER_THREAT_RADIUS_SQ = 16
CORE_TURRET_THREAT_RADIUS_SQ = 64
CORE_RESPONSE_RADIUS_SQ = 49
LANE_THREAT_RADIUS_SQ = 9
LANE_RESPONSE_RADIUS_SQ = 49
LANE_CORE_RESPONSE_RADIUS_SQ = 49
LANE_ASSET_DEFENSE_RADIUS_SQ = 9
LANE_PROACTIVE_BUILDER_RADIUS_SQ = 2
LANE_PROACTIVE_ASSET_CORE_RADIUS_SQ = 100
DEFENSE_SENTINEL_COOLDOWN = 12
MAX_VISIBLE_CORE_DEFENSE_SENTINELS = 1
MAX_VISIBLE_LANE_DEFENSE_SENTINELS = 1
CORE_PORT_RESPONSE_RADIUS_SQ = 100
CORE_PORT_THREAT_RADIUS_SQ = 100
CORE_PORT_CLOSE_BUILDER_RADIUS_SQ = 25
CORE_PORT_BARRIER_COOLDOWN = 20
MAX_VISIBLE_CORE_PORT_BARRIERS = 1
CORE_PORT_REPAIR_TYPES = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}
CORE_PORT_CLEAR_TYPES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.MARKER,
}

# Economy-health gate on defense builds. A sentinel costs 30 Ti to build and
# 10 Ti per shot, so a bot that panic-builds a sentinel before it has any
# delivery-connected harvester ends up with a useless gun starving for
# ammunition while the economy collapses. Only allow defense builds when
# there is at least one connected conveyor feeding the core (proof of a
# working delivery lane) OR the threat is extreme-close to the core (in
# which case a last-resort sentinel is still worth paying for).
DEFENSE_EMERGENCY_CORE_DIST_SQ = 8
DEFENSE_MIN_TITANIUM_RESERVE = GameConstants.SENTINEL_BASE_COST[0] + (
    GameConstants.SENTINEL_AMMO_COST * 3
)

DEFENSIVE_THREAT_TYPES = {
    EntityType.BUILDER_BOT,
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}

ECONOMY_DEFENSE_ASSET_TYPES = {
    EntityType.HARVESTER,
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}


def _pos_key(pos: Position) -> tuple[int, int]:
    return (pos.x, pos.y)


def _core_approach_slots(bot, ct: Controller) -> tuple[Position, ...]:
    """Return the 12 cardinal approach slots around the 3x3 core footprint."""
    core_pos = bot.core_pos
    if core_pos is None:
        return ()

    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    slots = []
    for dx, dy in (
        (-1, -2),
        (0, -2),
        (1, -2),
        (-1, 2),
        (0, 2),
        (1, 2),
        (-2, -1),
        (-2, 0),
        (-2, 1),
        (2, -1),
        (2, 0),
        (2, 1),
    ):
        pos = Position(core_pos.x + dx, core_pos.y + dy)
        if 0 <= pos.x < map_width and 0 <= pos.y < map_height:
            slots.append(pos)
    return tuple(slots)


def _is_own_direct_core_lane_tile(bot, pos: Position) -> bool:
    key = _pos_key(pos)
    if pos == getattr(bot, "core_lane_slot_pos", None):
        return True
    if pos == getattr(bot, "core_lane_core_tile_pos", None):
        return True
    if key in getattr(bot, "connected_friendly_conveyors", {}):
        return True
    if key in getattr(bot, "known_friendly_conveyors", set()):
        return True
    if key in getattr(bot, "claimed_pipeline_positions", set()):
        return True
    if key in getattr(bot, "tiled_back_positions", set()):
        return True
    return False


def _is_visible_open_barrier_tile(bot, ct: Controller, pos: Position, my_team) -> bool:
    key = _pos_key(pos)
    visible = getattr(bot, "visible_positions", None)
    if visible is not None and key not in visible:
        return False

    data = bot.grid.get(key)
    if data is None:
        return False
    if data.get("env") in utils.DO_NOT_BUILD_ON:
        return False
    if data.get("entity") is not None:
        return False
    if data.get("building") is not None:
        return False
    if pos in getattr(bot, "titanium_locations", set()):
        return False
    if pos in getattr(bot, "axionite_locations", set()):
        return False
    if _is_own_direct_core_lane_tile(bot, pos):
        return False
    return ct.can_build_barrier(pos)


def _visible_core_port_threats(bot, core_pos: Position, current_pos: Position):
    if bot.core_pos is None:
        return []

    threats = []
    for enemy in getattr(bot, "visible_enemy_targets", []):
        if enemy.entity_type not in DEFENSIVE_THREAT_TYPES:
            continue
        dist_sq = core_pos.distance_squared(enemy.position)
        if dist_sq > CORE_PORT_THREAT_RADIUS_SQ:
            continue
        threats.append(enemy)
    if not threats:
        return []
    threats.sort(
        key=lambda enemy: (
            core_pos.distance_squared(enemy.position),
            current_pos.distance_squared(enemy.position),
            enemy.position.x,
            enemy.position.y,
        )
    )
    return threats


def core_port_guard_if_needed(bot, ct: Controller) -> bool:
    """Tiny local guard for the core-side delivery ports.

    This is deliberately narrower than the normal lane-defense sentinel
    logic. Tootill-style rushes first contest the 12 approach tiles around
    the 3x3 core footprint, then place a gunner at distance 2-3 from the
    core. We only touch those approach slots and the current tile; no map
    scan, no pathfinding, and no fake shared coordination.
    """
    if bot.core_pos is None:
        return False
    if getattr(bot, "is_assault_role", False):
        return False
    if not getattr(bot, "visible_enemy_targets", None):
        return False
    core_pos = bot.core_pos
    current_pos = ct.get_position()
    if current_pos.distance_squared(core_pos) > CORE_PORT_RESPONSE_RADIUS_SQ:
        return False
    if getattr(bot, "builder_mode", None) == BuilderMode.TILING_BACK:
        return False

    my_team = ct.get_team()
    current_key = _pos_key(current_pos)
    current_data = bot.grid.get(current_key)
    if current_data is not None:
        current_building = current_data.get("building")
        current_team = current_data.get("building_team")
        if (
            current_building in CORE_PORT_CLEAR_TYPES
            and current_team is not None
            and current_team != my_team
            and core_pos.distance_squared(current_pos) <= CORE_PORT_THREAT_RADIUS_SQ
            and ct.can_fire(current_pos)
        ):
            ct.fire(current_pos)
            if utils.DEBUG:
                bot.logger.log(f"core-port clear hostile {current_building} at {current_pos}")
            return True

    threats = _visible_core_port_threats(bot, core_pos, current_pos)
    if not threats:
        return False

    approach_slots = _core_approach_slots(bot, ct)
    visible_barriers = 0
    for slot in approach_slots:
        data = bot.grid.get(_pos_key(slot))
        if data is None:
            continue
        if data.get("building") == EntityType.BARRIER and data.get("building_team") == my_team:
            visible_barriers += 1
        if data.get("building") not in CORE_PORT_REPAIR_TYPES:
            continue
        if data.get("building_team") != my_team:
            continue
        hp = data.get("building_hp")
        max_hp = data.get("building_max_hp")
        if hp is None or max_hp is None or hp >= max_hp:
            continue
        if ct.can_heal(slot):
            ct.heal(slot)
            bot.healing_this_turn = True
            if utils.DEBUG:
                bot.logger.log(f"core-port heal at {slot} ({hp}/{max_hp})")
            return True

    current_round = ct.get_current_round()
    if visible_barriers >= MAX_VISIBLE_CORE_PORT_BARRIERS:
        return False
    if current_round - getattr(bot, "last_core_port_barrier_round", -9999) < CORE_PORT_BARRIER_COOLDOWN:
        return False

    close_builders = [
        threat
        for threat in threats
        if threat.entity_type == EntityType.BUILDER_BOT
        and core_pos.distance_squared(threat.position)
        <= CORE_PORT_CLOSE_BUILDER_RADIUS_SQ
    ]
    if not close_builders:
        return False

    candidates = []
    for slot in approach_slots:
        if not _is_visible_open_barrier_tile(bot, ct, slot, my_team):
            continue
        best_threat_dist = min(
            slot.distance_squared(threat.position) for threat in close_builders
        )
        if best_threat_dist > 8:
            continue
        candidates.append(
            (
                best_threat_dist,
                core_pos.distance_squared(slot),
                current_pos.distance_squared(slot),
                slot.x,
                slot.y,
                slot,
            )
        )
    if not candidates:
        return False

    chosen = min(candidates)[5]
    ct.build_barrier(chosen)
    bot.last_core_port_barrier_round = current_round
    if utils.DEBUG:
        bot.logger.log(f"core-port barrier at {chosen}")
    return True

    return False


def _threat_key(bot, ct: Controller, threat) -> tuple[int, int, int, int]:
    current_pos = ct.get_position()
    return (
        bot.core_pos.distance_squared(threat.position),
        current_pos.distance_squared(threat.position),
        threat.position.x,
        threat.position.y,
    )


def _visible_core_threat(bot, ct: Controller):
    if bot.core_pos is None:
        return None

    # Avoid the list comprehension when there is nothing to scan. Inline
    # the loop so the cost is bounded by the actual number of visible
    # enemies and we can short-circuit on the first matching threat
    # without allocating an intermediate list.
    enemies = bot.visible_enemy_targets
    if not enemies:
        return None
    core_pos = bot.core_pos
    builder_radius = CORE_BUILDER_THREAT_RADIUS_SQ
    turret_radius = CORE_TURRET_THREAT_RADIUS_SQ
    builder_kind = EntityType.BUILDER_BOT
    threats = []
    for enemy in enemies:
        if enemy.entity_type not in DEFENSIVE_THREAT_TYPES:
            continue
        dist_sq = core_pos.distance_squared(enemy.position)
        if enemy.entity_type is builder_kind:
            if dist_sq > builder_radius:
                continue
        elif dist_sq > turret_radius:
            continue
        threats.append(enemy)
    if not threats:
        return None
    return min(threats, key=lambda threat: _threat_key(bot, ct, threat))


def _visible_core_defense_sentinel_count(bot, ct: Controller) -> int:
    my_team = ct.get_team()
    count = 0
    sentinel = EntityType.SENTINEL
    grid_get = bot.grid.get
    core_pos = bot.core_pos
    radius = CORE_RESPONSE_RADIUS_SQ
    visible = getattr(bot, "visible_positions", None) or ()
    for pos_key in visible:
        data = grid_get(pos_key)
        if data is None:
            continue
        if data.get("building") is not sentinel:
            continue
        if data.get("building_team") != my_team:
            continue
        sentinel_pos = Position(pos_key[0], pos_key[1])
        if core_pos.distance_squared(sentinel_pos) <= radius:
            count += 1
    return count


def _asset_has_visible_damage(bot, asset_pos: Position) -> bool:
    data = bot.grid.get((asset_pos.x, asset_pos.y))
    if data is None:
        return False
    hp = data.get("building_hp")
    max_hp = data.get("building_max_hp")
    return hp is not None and max_hp is not None and hp < max_hp


def _visible_lane_threat(
    bot,
    ct: Controller,
    *,
    require_builder_damage: bool,
    max_builder_asset_dist_sq: int | None = None,
    max_asset_core_dist_sq: int | None = None,
):
    current_pos = ct.get_position()
    if bot.core_pos is None:
        return None, None

    threats = [
        enemy
        for enemy in getattr(bot, "visible_enemy_targets", [])
        if enemy.entity_type in DEFENSIVE_THREAT_TYPES
        and current_pos.distance_squared(enemy.position) <= LANE_RESPONSE_RADIUS_SQ
    ]
    if not threats:
        return None, None

    my_team = ct.get_team()
    visible_assets = []
    grid_get = bot.grid.get
    asset_kinds = ECONOMY_DEFENSE_ASSET_TYPES
    radius = LANE_RESPONSE_RADIUS_SQ
    visible = getattr(bot, "visible_positions", None) or ()
    for pos_key in visible:
        data = grid_get(pos_key)
        if data is None:
            continue
        if data.get("building") not in asset_kinds:
            continue
        if data.get("building_team") != my_team:
            continue
        asset_pos = Position(pos_key[0], pos_key[1])
        if current_pos.distance_squared(asset_pos) > radius:
            continue
        visible_assets.append(asset_pos)

    if not visible_assets:
        return None, None

    best = None
    best_key = None
    for threat in threats:
        for asset_pos in visible_assets:
            if (
                max_asset_core_dist_sq is not None
                and asset_pos.distance_squared(bot.core_pos) > max_asset_core_dist_sq
            ):
                continue
            threat_asset_dist = threat.position.distance_squared(asset_pos)
            if threat_asset_dist > LANE_THREAT_RADIUS_SQ:
                continue
            if threat.entity_type == EntityType.BUILDER_BOT:
                if (
                    max_builder_asset_dist_sq is not None
                    and threat_asset_dist > max_builder_asset_dist_sq
                ):
                    continue
                if require_builder_damage and not _asset_has_visible_damage(
                    bot, asset_pos
                ):
                    continue
            candidate_key = (
                threat_asset_dist,
                current_pos.distance_squared(threat.position),
                asset_pos.distance_squared(bot.core_pos),
                threat.position.x,
                threat.position.y,
                asset_pos.x,
                asset_pos.y,
            )
            if best_key is not None and candidate_key >= best_key:
                continue
            best_key = candidate_key
            best = (threat, asset_pos)

    if best is None:
        return None, None
    return best


def _visible_lane_defense_sentinel_count(
    bot,
    ct: Controller,
    asset_pos: Position,
) -> int:
    my_team = ct.get_team()
    count = 0
    sentinel = EntityType.SENTINEL
    grid_get = bot.grid.get
    visible = getattr(bot, "visible_positions", None) or ()
    for pos_key in visible:
        data = grid_get(pos_key)
        if data is None:
            continue
        if data.get("building") is not sentinel:
            continue
        if data.get("building_team") != my_team:
            continue
        sentinel_pos = Position(pos_key[0], pos_key[1])
        if asset_pos.distance_squared(sentinel_pos) <= LANE_ASSET_DEFENSE_RADIUS_SQ:
            count += 1
    return count


_TRANSPORT_FEEDING_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
})


def _sentinel_supply_class(bot, ct: Controller, build_pos: Position) -> int:
    """Rank the quality of the ammo-supply options adjacent to a candidate
    sentinel tile. Guns need titanium to fire, so we must only build where
    a supply can physically reach the sentinel. Cardinal neighbours are
    checked; the sentinel tile itself is irrelevant because resources flow
    tile-to-tile along cardinal edges.

    Returns an integer priority (lower is better / more preferred):
      0 — adjacent enemy harvester we can steal by splicing a conveyor
          out of it. Free ammo, hurts the opponent.
      1 — adjacent friendly harvester already producing titanium.
      2 — adjacent connected friendly conveyor chain (already feeding
          our core, and a branch can feed this sentinel too).
      3 — adjacent friendly transport building that is NOT yet connected,
          but is at least a staging point for a lane.
      99 — no feeding source at all; build is forbidden."""
    my_team = ct.get_team()
    grid = bot.grid
    connected = getattr(bot, "connected_friendly_conveyors", {})

    best = 99
    for d in utils.CARDINAL_DIRECTIONS:
        neighbor = build_pos.add(d)
        data = grid.get((neighbor.x, neighbor.y))
        if not data:
            continue
        building = data.get("building")
        team = data.get("building_team")
        if building is EntityType.HARVESTER:
            if team == my_team:
                best = min(best, 1)
            elif team is not None and team != my_team:
                # Enemy harvester adjacent → we can steal it as a defense
                # supply. Strongest preference.
                best = min(best, 0)
            continue
        if building in _TRANSPORT_FEEDING_TYPES and team == my_team:
            if (neighbor.x, neighbor.y) in connected:
                best = min(best, 2)
            else:
                best = min(best, 3)
    return best


def _sentinel_build_candidates(bot, ct: Controller, threat_pos: Position):
    current_pos = ct.get_position()
    candidates = []
    for direction in utils.DIRECTIONS:
        build_pos = current_pos.add(direction)
        if not utils.in_bounds(ct, build_pos):
            continue
        if bot.core_pos is not None and max(
            abs(build_pos.x - bot.core_pos.x),
            abs(build_pos.y - bot.core_pos.y),
        ) <= 1:
            continue
        if (
            build_pos in getattr(bot, "titanium_locations", set())
            or build_pos in getattr(bot, "axionite_locations", set())
        ):
            continue
        sentinel_direction = build_pos.direction_to(threat_pos)
        if sentinel_direction is None:
            sentinel_direction = utils.direction_toward(build_pos, threat_pos)
        if not ct.can_build_sentinel(build_pos, sentinel_direction):
            continue
        supply_class = _sentinel_supply_class(bot, ct, build_pos)
        if supply_class >= 99:
            # No adjacent supply → this sentinel would starve for ammo on
            # turn 1. Skip it so we don't waste 30 Ti and divert a builder
            # from the work that would have BUILT a supply lane.
            continue
        candidates.append(
            (
                supply_class,  # prefer stolen enemy harvester > friendly harvester
                                # > connected conveyor > unconnected transport
                build_pos.distance_squared(threat_pos),
                bot.core_pos.distance_squared(build_pos) if bot.core_pos else 0,
                build_pos.x,
                build_pos.y,
                build_pos,
                sentinel_direction,
            )
        )
    return candidates


def _build_best_sentinel(
    bot,
    ct: Controller,
    threat_pos: Position,
    *,
    asset_pos: Position | None = None,
) -> bool:
    candidates = _sentinel_build_candidates(bot, ct, threat_pos)
    if not candidates:
        return False

    # Candidate tuple:
    #   (supply_class, dist_to_threat, dist_to_core, build_pos.x,
    #    build_pos.y, build_pos, sentinel_direction)
    # min() on the tuple preserves the supply-class priority first (stolen
    # enemy harvester > friendly harvester > connected conveyor), then
    # falls through to threat proximity etc.
    if asset_pos is None:
        chosen = min(candidates)
    else:
        chosen = min(
            candidates,
            key=lambda candidate: (
                candidate[0],  # supply class stays top priority
                candidate[1],  # dist to threat
                asset_pos.distance_squared(candidate[5]),
                candidate[2],  # dist to core
                candidate[3],
                candidate[4],
            ),
        )
    build_pos = chosen[5]
    sentinel_direction = chosen[6]

    ct.build_sentinel(build_pos, sentinel_direction)
    bot.last_defense_build_round = ct.get_current_round()
    supply_class = chosen[0]
    supply_label = {
        0: "stolen enemy harvester",
        1: "friendly harvester",
        2: "connected friendly conveyor",
        3: "unconnected friendly transport",
    }.get(supply_class, "unknown")
    if asset_pos is None:
        bot.logger.log(
            f"core defense sentinel at {build_pos} toward {threat_pos} "
            f"supply={supply_label}"
        )
    else:
        bot.logger.log(
            f"lane defense sentinel at {build_pos} protecting {asset_pos} "
            f"toward {threat_pos} supply={supply_label}"
        )
    return True


def _economy_can_support_defense(bot, ct: Controller, threat_pos: Position) -> bool:
    """Block panic-building a sentinel when the delivery economy can't feed
    it. A sentinel burns `SENTINEL_AMMO_COST` titanium per shot, so a bot
    that defends before there is a working delivery lane just torches its
    titanium reserve AND abandons the ore-hunt that would have built one.

    The gate lets the build proceed when any of the following holds:
      1. There is at least one friendly conveyor connected to the core
         (proof of a live delivery lane that can feed the turret),
      2. We already have a titanium reserve large enough to buy the
         sentinel plus several shots outright, or
      3. The threat is physically adjacent to the core, in which case a
         doomed last-stand sentinel is still better than nothing.
    """
    if threat_pos is not None and bot.core_pos is not None:
        core_dist_sq = bot.core_pos.distance_squared(threat_pos)
        if core_dist_sq <= DEFENSE_EMERGENCY_CORE_DIST_SQ:
            return True

    if getattr(bot, "connected_friendly_conveyors", None):
        return True

    try:
        team_ti, _ = ct.get_global_resources()
    except Exception:
        team_ti = 0
    if team_ti >= DEFENSE_MIN_TITANIUM_RESERVE:
        return True

    return False


def defend_core_if_needed(bot, ct: Controller) -> bool:
    if getattr(bot, "is_assault_role", False):
        return False
    if bot.builder_mode not in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
        return False
    if bot.core_pos is None:
        return False
    # Hot path early-out: no visible enemies → no possible threat. The
    # subsequent walks over visible_positions are skipped entirely.
    if not bot.visible_enemy_targets:
        return False

    current_round = ct.get_current_round()
    if (
        current_round - getattr(bot, "last_defense_build_round", -9999)
        < DEFENSE_SENTINEL_COOLDOWN
    ):
        return False

    current_pos = ct.get_position()
    if current_pos.distance_squared(bot.core_pos) <= CORE_RESPONSE_RADIUS_SQ:
        threat = _visible_core_threat(bot, ct)
        if threat is not None:
            if (
                _visible_core_defense_sentinel_count(bot, ct)
                < MAX_VISIBLE_CORE_DEFENSE_SENTINELS
            ) and _economy_can_support_defense(bot, ct, threat.position):
                return _build_best_sentinel(bot, ct, threat.position)
            return False

    return False


def defend_lane_if_needed(bot, ct: Controller) -> bool:
    if getattr(bot, "is_assault_role", False):
        return False
    if bot.builder_mode not in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
        return False
    if bot.core_pos is None:
        return False
    # Same hot-path early-out as defend_core_if_needed.
    if not bot.visible_enemy_targets:
        return False

    current_round = ct.get_current_round()
    if (
        current_round - getattr(bot, "last_defense_build_round", -9999)
        < DEFENSE_SENTINEL_COOLDOWN
    ):
        return False

    current_pos = ct.get_position()
    if current_pos.distance_squared(bot.core_pos) > LANE_CORE_RESPONSE_RADIUS_SQ:
        return False
    lane_threat, asset_pos = _visible_lane_threat(
        bot,
        ct,
        require_builder_damage=True,
    )
    if lane_threat is None or asset_pos is None:
        # Early rushes often sit next to a harvester or first-lane conveyor
        # before visible damage is refreshed. Treat only adjacent/diagonal
        # enemy builders near the core-side economy as proactive threats; the
        # fed-site and sentinel-count gates below still have to pass.
        lane_threat, asset_pos = _visible_lane_threat(
            bot,
            ct,
            require_builder_damage=False,
            max_builder_asset_dist_sq=LANE_PROACTIVE_BUILDER_RADIUS_SQ,
            max_asset_core_dist_sq=LANE_PROACTIVE_ASSET_CORE_RADIUS_SQ,
        )
    if lane_threat is None or asset_pos is None:
        return False
    if (
        _visible_lane_defense_sentinel_count(bot, ct, asset_pos)
        >= MAX_VISIBLE_LANE_DEFENSE_SENTINELS
    ):
        return False
    if not _economy_can_support_defense(bot, ct, lane_threat.position):
        return False

    return _build_best_sentinel(
        bot,
        ct,
        lane_threat.position,
        asset_pos=asset_pos,
    )
