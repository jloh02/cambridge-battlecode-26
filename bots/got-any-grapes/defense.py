from cambc import Controller, EntityType, Position
from states import BuilderMode
import utils


CORE_BUILDER_THREAT_RADIUS_SQ = 16
CORE_TURRET_THREAT_RADIUS_SQ = 64
CORE_RESPONSE_RADIUS_SQ = 49
LANE_THREAT_RADIUS_SQ = 9
LANE_RESPONSE_RADIUS_SQ = 49
LANE_CORE_RESPONSE_RADIUS_SQ = 49
LANE_ASSET_DEFENSE_RADIUS_SQ = 9
DEFENSE_SENTINEL_COOLDOWN = 12
MAX_VISIBLE_CORE_DEFENSE_SENTINELS = 1
MAX_VISIBLE_LANE_DEFENSE_SENTINELS = 1

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

    threats = [
        enemy
        for enemy in getattr(bot, "visible_enemy_targets", [])
        if enemy.entity_type in DEFENSIVE_THREAT_TYPES
        and (
            (
                enemy.entity_type == EntityType.BUILDER_BOT
                and bot.core_pos.distance_squared(enemy.position)
                <= CORE_BUILDER_THREAT_RADIUS_SQ
            )
            or (
                enemy.entity_type != EntityType.BUILDER_BOT
                and bot.core_pos.distance_squared(enemy.position)
                <= CORE_TURRET_THREAT_RADIUS_SQ
            )
        )
    ]
    if not threats:
        return None
    return min(threats, key=lambda threat: _threat_key(bot, ct, threat))


def _visible_core_defense_sentinel_count(bot, ct: Controller) -> int:
    my_team = ct.get_team()
    count = 0
    for pos_key in getattr(bot, "visible_positions", set()):
        data = bot.grid.get(pos_key, {})
        if data.get("building") != EntityType.SENTINEL:
            continue
        if data.get("building_team") != my_team:
            continue
        sentinel_pos = Position(pos_key[0], pos_key[1])
        if bot.core_pos.distance_squared(sentinel_pos) <= CORE_RESPONSE_RADIUS_SQ:
            count += 1
    return count


def _asset_has_visible_damage(bot, asset_pos: Position) -> bool:
    data = bot.grid.get((asset_pos.x, asset_pos.y), {})
    hp = data.get("building_hp")
    max_hp = data.get("building_max_hp")
    return hp is not None and max_hp is not None and hp < max_hp


def _visible_lane_threat(bot, ct: Controller, *, require_builder_damage: bool):
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
    for pos_key in getattr(bot, "visible_positions", set()):
        data = bot.grid.get(pos_key, {})
        if data.get("building") not in ECONOMY_DEFENSE_ASSET_TYPES:
            continue
        if data.get("building_team") != my_team:
            continue
        asset_pos = Position(pos_key[0], pos_key[1])
        if current_pos.distance_squared(asset_pos) > LANE_RESPONSE_RADIUS_SQ:
            continue
        visible_assets.append(asset_pos)

    if not visible_assets:
        return None, None

    best = None
    best_key = None
    for threat in threats:
        for asset_pos in visible_assets:
            threat_asset_dist = threat.position.distance_squared(asset_pos)
            if threat_asset_dist > LANE_THREAT_RADIUS_SQ:
                continue
            if (
                require_builder_damage
                and threat.entity_type == EntityType.BUILDER_BOT
                and not _asset_has_visible_damage(bot, asset_pos)
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
    for pos_key in getattr(bot, "visible_positions", set()):
        data = bot.grid.get(pos_key, {})
        if data.get("building") != EntityType.SENTINEL:
            continue
        if data.get("building_team") != my_team:
            continue
        sentinel_pos = Position(pos_key[0], pos_key[1])
        if asset_pos.distance_squared(sentinel_pos) <= LANE_ASSET_DEFENSE_RADIUS_SQ:
            count += 1
    return count


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
        candidates.append(
            (
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

    if asset_pos is None:
        _, _, _, _, build_pos, sentinel_direction = min(candidates)
    else:
        _, _, _, _, build_pos, sentinel_direction = min(
            candidates,
            key=lambda candidate: (
                candidate[0],
                asset_pos.distance_squared(candidate[4]),
                candidate[1],
                candidate[2],
                candidate[3],
            ),
        )

    ct.build_sentinel(build_pos, sentinel_direction)
    bot.last_defense_build_round = ct.get_current_round()
    if asset_pos is None:
        bot.logger.log(
            f"core defense sentinel at {build_pos} toward {threat_pos}"
        )
    else:
        bot.logger.log(
            f"lane defense sentinel at {build_pos} protecting {asset_pos} toward {threat_pos}"
        )
    return True


def defend_core_if_needed(bot, ct: Controller) -> bool:
    if getattr(bot, "is_assault_role", False):
        return False
    if bot.builder_mode not in {BuilderMode.FINDING_ORE, BuilderMode.EXPLORING}:
        return False
    if bot.core_pos is None:
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
            ):
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
        return False
    if (
        _visible_lane_defense_sentinel_count(bot, ct, asset_pos)
        >= MAX_VISIBLE_LANE_DEFENSE_SENTINELS
    ):
        return False

    return _build_best_sentinel(
        bot,
        ct,
        lane_threat.position,
        asset_pos=asset_pos,
    )
