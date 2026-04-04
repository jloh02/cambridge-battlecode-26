from __future__ import annotations

from cambc import Controller, Direction, EntityType, Environment, Position

import assault
import marker
import navigation
import perception
import utils


ASSAULT_OBJECTIVE_TTL = 16
ASSAULT_RECENT_CONFIRM_TTL = 16
ASSAULT_STALL_TTL = 10
ASSAULT_BLACKLIST_TTL = 28
ASSAULT_GOOD_ENOUGH_TTL = 12
ASSAULT_LOCAL_STALL_RADIUS_SQ = 49
ASSAULT_ADJACENT_WAIT_TTL = 3
ASSAULT_SCOUT_CHUNK_STALE_CAP = 24
ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ = 4
ASSAULT_SCOUT_TARGET_TTL = 18
ASSAULT_CLAIM_REFRESH_INTERVAL = 4
RECENT_WAYPOINT_TTL = 12
ASSAULT_GLOBAL_FRONTIER_STALE_MIN = max(2, perception.CHUNK_SIZE)


def _clear_adjacent_wait(bot) -> None:
    bot.assault_wait_state = {
        "site_signature": None,
        "staging_position": None,
        "expires_round": -1,
    }


def _clear_scout_state(bot) -> None:
    bot.assault_scout_state = {
        "target": None,
        "chunk": None,
        "anchor": None,
        "expires_round": -1,
    }


def _clear_anchor(bot) -> None:
    bot.harvester_anchor = None
    bot.harvester_anchor_last_seen_round = -9999
    bot.assault_anchor_status = None
    bot.assault_last_site_signature = None
    bot.assault_subrole = "support"
    _clear_adjacent_wait(bot)


def _anchor_blacklist_ttl(reason: str) -> int:
    normalized_reason = _normalize_reason(reason)
    if normalized_reason == assault.ANCHOR_GOOD_ENOUGH:
        return ASSAULT_GOOD_ENOUGH_TTL
    return ASSAULT_BLACKLIST_TTL


def _normalize_reason(reason: str) -> str:
    return reason.strip().upper().replace(" ", "_")


def _marks_sector_exhausted(reason: str) -> bool:
    normalized_reason = _normalize_reason(reason)
    return normalized_reason in {
        _normalize_reason(assault.ANCHOR_CAPTURED),
        _normalize_reason(assault.ANCHOR_DRIED),
        _normalize_reason(assault.ANCHOR_SATURATED),
    }


def _refresh_anchor_blacklist(bot, current_round: int) -> None:
    anchor_blacklist = getattr(bot, "assault_anchor_blacklist", {})
    bot.assault_anchor_blacklist = {
        key: expiry_round
        for key, expiry_round in anchor_blacklist.items()
        if expiry_round > current_round
    }


def _refresh_exhausted_regions(bot, current_round: int) -> None:
    bot.assault_exhausted_regions = [
        region
        for region in getattr(bot, "assault_exhausted_regions", [])
        if region.get("expires_round", -1) > current_round
    ]


def _refresh_exhausted_sectors(bot, current_round: int) -> None:
    bot.assault_exhausted_sectors = {
        key: expiry_round
        for key, expiry_round in getattr(bot, "assault_exhausted_sectors", {}).items()
        if expiry_round > current_round
    }


def _is_anchor_blacklisted(bot, position: Position, current_round: int) -> bool:
    return (
        getattr(bot, "assault_anchor_blacklist", {}).get((position.x, position.y), -1)
        > current_round
    )


def _is_in_exhausted_region(bot, position: Position, current_round: int) -> bool:
    for region in getattr(bot, "assault_exhausted_regions", []):
        if region.get("expires_round", -1) <= current_round:
            continue
        cluster_positions = region.get("cluster_positions")
        if cluster_positions and (position.x, position.y) in cluster_positions:
            return True
        anchor = region.get("anchor")
        if anchor is None:
            continue
        anchor_position = Position(anchor[0], anchor[1])
        if assault.manhattan(position, anchor_position) <= 4:
            return True
    return False


def _blacklist_anchor(
    bot,
    position: Position,
    current_round: int,
    *,
    ttl: int,
) -> None:
    if not hasattr(bot, "assault_anchor_blacklist"):
        bot.assault_anchor_blacklist = {}
    bot.assault_anchor_blacklist[(position.x, position.y)] = current_round + ttl


def _assault_sector_span(ct: Controller) -> int:
    base_span = max(1, perception.CHUNK_SIZE * 2)
    max_dim = max(ct.get_map_width(), ct.get_map_height())
    return min(max_dim, max(base_span, max_dim // 4))


def _use_frontier_scouting(ct: Controller) -> bool:
    return max(ct.get_map_width(), ct.get_map_height()) >= 28


def _sector_key(ct: Controller, position: Position) -> tuple[int, int]:
    span = _assault_sector_span(ct)
    return (position.x // span, position.y // span)


def _sector_blacklist_ttl(ct: Controller, reason: str) -> int:
    if not _use_frontier_scouting(ct):
        return _anchor_blacklist_ttl(reason)
    return max(_anchor_blacklist_ttl(reason), perception.CHUNK_SIZE * 12)


def _record_exhausted_sector(
    bot,
    ct: Controller,
    position: Position,
    *,
    current_round: int,
    ttl: int,
) -> None:
    if ttl <= 0:
        return
    sector = _sector_key(ct, position)
    current_expiry = getattr(bot, "assault_exhausted_sectors", {}).get(sector, -1)
    expiry_round = current_round + ttl
    if expiry_round <= current_expiry:
        return
    bot.assault_exhausted_sectors[sector] = expiry_round


def _is_in_exhausted_sector(
    bot,
    ct: Controller,
    position: Position,
    current_round: int,
) -> bool:
    if not _use_frontier_scouting(ct):
        return False
    return getattr(bot, "assault_exhausted_sectors", {}).get(
        _sector_key(ct, position),
        -1,
    ) > current_round


def _is_locally_claimed_assault_anchor(bot, position: Position) -> bool:
    return (position.x, position.y) in getattr(
        bot,
        "claimed_assault_anchor_keys",
        set(),
    )


def _publish_assault_claim(bot, ct: Controller, anchor: Position) -> None:
    current_round = ct.get_current_round()
    anchor_key = (anchor.x, anchor.y)
    claim_state = getattr(bot, "assault_claim_state", {})
    if (
        claim_state.get("anchor") == anchor_key
        and current_round - claim_state.get("last_round", -9999)
        < ASSAULT_CLAIM_REFRESH_INTERVAL
    ):
        return

    marker_value = marker.create_assault_claim_marker(
        anchor,
        marker.assault_claim_owner_tag(ct.get_id()),
        current_round,
        ct.get_map_width(),
        ct.get_map_height(),
    )
    if utils.place_marker_around(ct, ct.get_position(), marker_value):
        bot.assault_claim_state = {
            "anchor": anchor_key,
            "last_round": current_round,
        }


def _record_exhausted_region(
    bot,
    position: Position,
    *,
    enemies: list[assault.VisibleEnemy],
    current_round: int,
    ttl: int,
) -> None:
    if ttl <= 0:
        return
    cluster_positions = None
    if any(
        enemy.entity_type == EntityType.HARVESTER and enemy.position == position
        for enemy in enemies
    ):
        cluster = assault.connected_enemy_logistics_cluster(position, enemies)
        if cluster:
            cluster_positions = {(tile.x, tile.y) for tile in cluster}
    bot.assault_exhausted_regions.append(
        {
            "anchor": (position.x, position.y),
            "cluster_positions": cluster_positions,
            "expires_round": current_round + ttl,
        }
    )


def _retire_anchor(bot, ct: Controller, position: Position, *, reason: str) -> None:
    bot.logger.log(f"retiring anchor {position} because {reason}")
    current_round = ct.get_current_round()
    ttl = _anchor_blacklist_ttl(reason)
    _blacklist_anchor(bot, position, current_round, ttl=ttl)
    _record_exhausted_region(
        bot,
        position,
        enemies=_assault_enemies(bot),
        current_round=current_round,
        ttl=ttl,
    )
    if _marks_sector_exhausted(reason):
        _record_exhausted_sector(
            bot,
            ct,
            position,
            current_round=current_round,
            ttl=_sector_blacklist_ttl(ct, reason),
        )
    _clear_anchor(bot)
    _clear_scout_state(bot)


def _anchor_assessment(
    bot,
    ct: Controller,
    anchor: Position,
    *,
    enemies: list[assault.VisibleEnemy] | None = None,
) -> assault.AnchorAssessment:
    current_enemies = _assault_enemies(bot) if enemies is None else enemies
    return assault.assess_anchor(
        harvester_position=anchor,
        current_position=ct.get_position(),
        enemies=current_enemies,
        grid=bot.grid,
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct)
        | _visible_friendly_ring_sentinels(bot, ct, anchor),
        legal_fire_fn=_legal_fire_fn(ct),
        enemy_core_center=_visible_enemy_core_center(current_enemies),
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
        friendly_builder_positions=getattr(bot, "visible_friendly_builders", []),
    )


def _site_signature(site: assault.AssaultSite) -> tuple[object, ...]:
    return (
        site.harvester_position.x,
        site.harvester_position.y,
        site.ring_position.x,
        site.ring_position.y,
        site.sentinel_direction.name,
    )


def _is_locally_stalled(bot, ct: Controller, anchor: Position) -> bool:
    return _is_locally_stalled_for_site(bot, ct, anchor, site=None)


def _is_locally_stalled_for_site(
    bot,
    ct: Controller,
    anchor: Position,
    *,
    site: assault.AssaultSite | None,
) -> bool:
    if site is not None:
        current_pos = ct.get_position()
        if (
            max(
                abs(current_pos.x - site.ring_position.x),
                abs(current_pos.y - site.ring_position.y),
            )
            <= 1
            and _is_clearable_enemy_conveyor(bot, ct, site.ring_position)
        ):
            return False
    return (
        ct.get_position().distance_squared(anchor) <= ASSAULT_LOCAL_STALL_RADIUS_SQ
        and ct.get_current_round() - bot.assault_last_progress_round > ASSAULT_STALL_TTL
    )


def _legal_fire_fn(ct: Controller):
    if not hasattr(ct, "can_fire_from"):
        return None

    def _legal(position: Position, direction: Direction, target: Position) -> bool:
        try:
            return ct.can_fire_from(position, direction, EntityType.SENTINEL, target)
        except Exception:
            return False

    return _legal


def _assault_enemies(bot) -> list[assault.VisibleEnemy]:
    return list(getattr(bot, "visible_enemy_targets", []))


def _visible_enemy_core_center(enemies: list[assault.VisibleEnemy]) -> Position | None:
    for enemy in enemies:
        if enemy.entity_type == EntityType.CORE:
            return enemy.position
    return None


def _arm_adjacent_wait(
    bot,
    ct: Controller,
    site: assault.AssaultSite,
    *,
    staging_position: Position,
) -> None:
    if assault.manhattan(staging_position, site.harvester_position) <= 1:
        _clear_adjacent_wait(bot)
        return
    bot.assault_wait_state = {
        "site_signature": _site_signature(site),
        "staging_position": (staging_position.x, staging_position.y),
        "expires_round": ct.get_current_round() + ASSAULT_ADJACENT_WAIT_TTL,
    }


def _can_afford_sentinel(ct: Controller) -> bool:
    get_global_resources = getattr(ct, "get_global_resources", None)
    get_sentinel_cost = getattr(ct, "get_sentinel_cost", None)
    if not callable(get_global_resources) or not callable(get_sentinel_cost):
        return False
    try:
        have_ti, have_ax = get_global_resources()
        need_ti, need_ax = get_sentinel_cost()
    except Exception:
        return False
    return have_ti >= need_ti and have_ax >= need_ax


def _should_hold_adjacent_wait(
    bot,
    ct: Controller,
    site: assault.AssaultSite,
) -> bool:
    wait_state = getattr(bot, "assault_wait_state", {})
    if wait_state.get("site_signature") != _site_signature(site):
        return False
    if wait_state.get("expires_round", -1) < ct.get_current_round():
        _clear_adjacent_wait(bot)
        return False

    current_pos = ct.get_position()
    if wait_state.get("staging_position") != (current_pos.x, current_pos.y):
        _clear_adjacent_wait(bot)
        return False
    if assault.manhattan(current_pos, site.harvester_position) <= 1:
        _clear_adjacent_wait(bot)
        return False
    if max(
        abs(current_pos.x - site.ring_position.x),
        abs(current_pos.y - site.ring_position.y),
    ) > 1:
        _clear_adjacent_wait(bot)
        return False
    if _tile_has_friendly_sentinel_now(ct, site.ring_position):
        _clear_adjacent_wait(bot)
        return False
    if _tile_has_other_builder_now(ct, site.ring_position):
        _clear_adjacent_wait(bot)
        return False
    if _is_clearable_enemy_conveyor(bot, ct, site.ring_position):
        _clear_adjacent_wait(bot)
        return False
    if ct.can_build_sentinel(site.ring_position, site.sentinel_direction):
        _clear_adjacent_wait(bot)
        return False

    get_action_cooldown = getattr(ct, "get_action_cooldown", None)
    if callable(get_action_cooldown):
        try:
            if get_action_cooldown() > 0:
                return True
        except Exception:
            pass
    return _can_afford_sentinel(ct)


def _blocked_ring_positions(bot, ct: Controller) -> set[Position]:
    blocked = set()
    for pos_tuple in getattr(bot, "visible_positions", set()):
        data = bot.grid.get(pos_tuple, {})
        if (
            data.get("building") == EntityType.SENTINEL
            and data.get("building_team") == ct.get_team()
        ):
            blocked.add(Position(pos_tuple[0], pos_tuple[1]))
    return blocked


def _visible_friendly_ring_sentinels(bot, ct: Controller, anchor: Position) -> set[Position]:
    positions = set()
    for direction in assault.CARDINAL_DIRECTIONS:
        ring_position = anchor.add(direction)
        data = bot.grid.get((ring_position.x, ring_position.y), {})
        if (
            data.get("building") == EntityType.SENTINEL
            and data.get("building_team") == ct.get_team()
        ):
            positions.add(ring_position)
    return positions


def _is_enemy_building_on_tile(
    bot,
    ct: Controller,
    position: Position,
    *,
    entity_types: set[EntityType],
) -> bool:
    data = bot.grid.get((position.x, position.y), {})
    return (
        data.get("building") in entity_types
        and data.get("building_team") is not None
        and data.get("building_team") != ct.get_team()
    )


def _is_clearable_enemy_conveyor(bot, ct: Controller, position: Position) -> bool:
    return _is_enemy_building_on_tile(
        bot,
        ct,
        position,
        entity_types={
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        },
    )


def _is_harassable_enemy_building(bot, ct: Controller, position: Position) -> bool:
    return _is_enemy_building_on_tile(
        bot,
        ct,
        position,
        entity_types=assault.HARASSABLE_PASSABLE_BUILDINGS,
    )


def _best_sidestep(
    bot,
    ct: Controller,
    blocked_position: Position,
    anchor: Position,
) -> Position | None:
    candidates = []
    for direction in utils.DIRECTIONS:
        candidate = blocked_position.add(direction)
        if not utils.in_bounds(ct, candidate):
            continue
        if candidate == anchor:
            continue
        if not utils.is_passable(bot, ct, blocked_position, direction):
            continue
        data = bot.grid.get((candidate.x, candidate.y), {})
        if (
            data.get("entity") == EntityType.BUILDER_BOT
            and data.get("entity_team") == ct.get_team()
        ):
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (
            0 if assault.manhattan(candidate, anchor) > 1 else 1,
            assault.manhattan(candidate, anchor),
            candidate.x,
            candidate.y,
        ),
    )


def _refresh_recent_waypoints(bot, current_round: int) -> None:
    bot.recent_assault_waypoints = {
        key: seen_round
        for key, seen_round in bot.recent_assault_waypoints.items()
        if current_round - seen_round <= RECENT_WAYPOINT_TTL
    }


def _candidate_ore_sources(bot) -> set[Position]:
    connected_harvesters = {
        Position(x, y) for x, y in getattr(bot, "known_connected_harvesters", set())
    }
    if not connected_harvesters:
        return set(bot.titanium_locations)

    candidates = {
        ore_pos
        for ore_pos in bot.titanium_locations
        if any(assault.manhattan(ore_pos, harvester) <= 8 for harvester in connected_harvesters)
    }
    if candidates:
        return candidates

    ordered = sorted(
        bot.titanium_locations,
        key=lambda position: (
            assault.manhattan(position, bot.core_pos or position),
            position.x,
            position.y,
        ),
    )
    return set(ordered[:6])


def _update_enemy_inference(bot, ct: Controller) -> None:
    current_round = ct.get_current_round()
    _refresh_recent_waypoints(bot, current_round)
    enemies = _assault_enemies(bot)

    if bot.last_enemy_core_position is not None:
        bot.enemy_core_anchor = bot.last_enemy_core_position
        bot.enemy_core_exact = True
    elif current_round - bot.last_symmetry_update_round >= 8:
        surviving, best_mode, confidence, _ = assault.evaluate_symmetry_modes(
            grid=bot.grid,
            map_width=ct.get_map_width(),
            map_height=ct.get_map_height(),
            core_pos=bot.core_pos,
            previous_modes=tuple(bot.symmetry_candidates),
        )
        if surviving:
            bot.symmetry_candidates = surviving
        if best_mode is not None:
            bot.best_symmetry_mode = best_mode
        bot.symmetry_confidence = confidence
        bot.last_symmetry_update_round = current_round

    if (
        not bot.enemy_core_exact
        and bot.core_pos is not None
        and bot.best_symmetry_mode is not None
    ):
        bot.enemy_core_anchor = assault.mirror_position(
            bot.core_pos,
            bot.best_symmetry_mode,
            map_width=ct.get_map_width(),
            map_height=ct.get_map_height(),
        )

    bot.confirmed_enemy_harvesters = assault.prune_confirmed_enemy_harvesters(
        confirmed_enemy_harvesters=bot.confirmed_enemy_harvesters,
        current_round=current_round,
        visible_positions=set(getattr(bot, "visible_positions", set())),
        enemies=enemies,
    )

    connected_harvesters = {
        Position(x, y) for x, y in getattr(bot, "known_connected_harvesters", set())
    }
    connected_harvesters.update(
        assault.connected_friendly_harvesters(
            grid=bot.grid,
            my_team=ct.get_team(),
            connected_conveyors=bot.connected_friendly_conveyors,
        )
    )
    bot.known_connected_harvesters.update(
        (position.x, position.y) for position in connected_harvesters
    )

    confirmed_positions = {
        Position(x, y) for x, y in bot.confirmed_enemy_harvesters
    }
    bot.predicted_enemy_harvesters = assault.build_predicted_enemy_harvesters(
        current_position=ct.get_position(),
        grid=bot.grid,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        my_team=ct.get_team(),
        surviving_modes=tuple(bot.symmetry_candidates),
        best_mode=bot.best_symmetry_mode,
        enemy_core_anchor=bot.enemy_core_anchor,
        connected_friendly_harvesters=connected_harvesters,
        remembered_ores=_candidate_ore_sources(bot),
        confirmed_enemy_harvesters=confirmed_positions,
        current_anchor=bot.harvester_anchor,
    )


def _live_anchor(bot, ct: Controller, enemies: list[assault.VisibleEnemy]) -> Position | None:
    anchor = bot.harvester_anchor
    if anchor is None:
        return None
    if _is_anchor_blacklisted(bot, anchor, ct.get_current_round()):
        _clear_anchor(bot)
        return None

    visible_enemy_harvesters = {
        enemy.position
        for enemy in enemies
        if enemy.entity_type == EntityType.HARVESTER
    }
    anchor_key = (anchor.x, anchor.y)
    if anchor in visible_enemy_harvesters:
        bot.harvester_anchor_last_seen_round = ct.get_current_round()
        return anchor

    if anchor_key in getattr(bot, "visible_positions", set()):
        _clear_anchor(bot)
        return None

    if ct.get_current_round() - bot.harvester_anchor_last_seen_round > ASSAULT_OBJECTIVE_TTL:
        _clear_anchor(bot)
        return None

    return anchor


def _recent_confirmed_anchor(bot, ct: Controller) -> Position | None:
    current_round = ct.get_current_round()
    current_position = ct.get_position()
    best: tuple[tuple[int, int, int, int, int], Position] | None = None

    for position_key, seen_round in bot.confirmed_enemy_harvesters.items():
        age = current_round - seen_round
        if age > ASSAULT_RECENT_CONFIRM_TTL:
            continue
        position = Position(position_key[0], position_key[1])
        if _is_anchor_blacklisted(bot, position, current_round):
            continue
        if _is_locally_claimed_assault_anchor(bot, position):
            continue
        score = (
            0 if bot.harvester_anchor == position else 1,
            age,
            assault.manhattan(current_position, position),
            position.x,
            position.y,
        )
        if best is None or score < best[0]:
            best = (score, position)

    return None if best is None else best[1]


def _committed_anchor(bot, ct: Controller, enemies: list[assault.VisibleEnemy]) -> Position | None:
    anchor = _live_anchor(bot, ct, enemies)
    if anchor is not None:
        return anchor

    recent_anchor = _recent_confirmed_anchor(bot, ct)
    if recent_anchor is None:
        return None

    recent_seen_round = bot.confirmed_enemy_harvesters.get(
        (recent_anchor.x, recent_anchor.y),
        ct.get_current_round(),
    )
    bot.harvester_anchor = recent_anchor
    bot.harvester_anchor_last_seen_round = recent_seen_round
    if bot.assault_last_progress_round < recent_seen_round:
        bot.assault_last_progress_round = recent_seen_round
    return recent_anchor


def _best_site_for_anchor(bot, ct: Controller, anchor: Position) -> assault.AssaultSite | None:
    if _is_anchor_blacklisted(bot, anchor, ct.get_current_round()):
        return None
    if _is_locally_claimed_assault_anchor(bot, anchor):
        return None
    enemies = _assault_enemies(bot)
    return assault.choose_best_site_for_harvester(
        harvester_position=anchor,
        current_position=ct.get_position(),
        enemies=enemies,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        grid=bot.grid,
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct)
        | _visible_friendly_ring_sentinels(bot, ct, anchor),
        legal_fire_fn=_legal_fire_fn(ct),
        enemy_core_center=_visible_enemy_core_center(enemies),
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
    )


def _best_visible_site(
    bot,
    ct: Controller,
    live_anchor: Position | None,
) -> assault.AssaultSite | None:
    enemies = _assault_enemies(bot)
    if not enemies:
        return None
    current_round = ct.get_current_round()
    ignored_harvesters: set[Position] = {
        Position(x, y)
        for x, y in getattr(bot, "claimed_assault_anchor_keys", set())
    }
    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        if _is_anchor_blacklisted(bot, enemy.position, current_round) or _is_in_exhausted_region(
            bot,
            enemy.position,
            current_round,
        ):
            ignored_harvesters.add(enemy.position)
            continue
        assessment = _anchor_assessment(bot, ct, enemy.position, enemies=enemies)
        if assessment.status != assault.ANCHOR_LIVE:
            ignored_harvesters.add(enemy.position)
    return assault.choose_best_visible_assault_site(
        current_position=ct.get_position(),
        enemies=enemies,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        grid=bot.grid,
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct),
        legal_fire_fn=_legal_fire_fn(ct),
        enemy_core_center=_visible_enemy_core_center(enemies),
        current_anchor=live_anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
        ignored_harvesters=ignored_harvesters,
    )


def _move_toward(
    bot,
    ct: Controller,
    target: Position,
    *,
    build_road: bool = True,
    allow_enemy_builder_at_target: bool = False,
) -> None:
    bot.logger.log(f"assault moving toward {target}")
    if navigation.assault_move_towards(
        bot,
        ct,
        target,
        build_road=build_road,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    ):
        return
    utils.move_random(ct)


def _tile_has_friendly_sentinel_now(ct: Controller, position: Position) -> bool:
    building_id = ct.get_tile_building_id(position)
    if building_id is None:
        return False
    return (
        ct.get_entity_type(building_id) == EntityType.SENTINEL
        and ct.get_team(building_id) == ct.get_team()
    )


def _tile_has_other_builder_now(ct: Controller, position: Position) -> bool:
    get_tile_builder_bot_id = getattr(ct, "get_tile_builder_bot_id", None)
    if get_tile_builder_bot_id is None:
        return False
    builder_id = get_tile_builder_bot_id(position)
    return builder_id is not None and builder_id != ct.get_id()


def _destroy_friendly_passable_building_if_present(
    ct: Controller,
    position: Position,
) -> bool:
    building_id = ct.get_tile_building_id(position)
    if building_id is None:
        return False
    if ct.get_team(building_id) != ct.get_team():
        return False
    if ct.get_entity_type(building_id) not in {
        EntityType.ROAD,
        EntityType.MARKER,
    }:
        return False
    if not ct.can_destroy(position):
        return False
    ct.destroy(position)
    return True


def _execute_site(bot, ct: Controller, site: assault.AssaultSite) -> bool:
    bot.harvester_anchor = site.harvester_position
    bot.harvester_anchor_last_seen_round = ct.get_current_round()

    current_pos = ct.get_position()
    ring_position = site.ring_position
    if current_pos == ring_position:
        if _is_clearable_enemy_conveyor(bot, ct, ring_position) and ct.can_fire(current_pos):
            ct.fire(current_pos)
            bot.assault_last_progress_round = ct.get_current_round()
            return True
        sidestep = _best_sidestep(bot, ct, ring_position, site.harvester_position)
        if sidestep is not None:
            move_dir = current_pos.direction_to(sidestep)
            if ct.can_move(move_dir):
                _arm_adjacent_wait(bot, ct, site, staging_position=sidestep)
                ct.move(move_dir)
                bot.assault_last_progress_round = ct.get_current_round()
                return True
        _clear_adjacent_wait(bot)
        return False

    if max(abs(current_pos.x - ring_position.x), abs(current_pos.y - ring_position.y)) <= 1:
        if _is_clearable_enemy_conveyor(bot, ct, ring_position):
            _clear_adjacent_wait(bot)
            _move_toward(bot, ct, ring_position, allow_enemy_builder_at_target=True)
            return True
        _destroy_friendly_passable_building_if_present(ct, ring_position)
        if ct.can_build_sentinel(ring_position, site.sentinel_direction):
            _clear_adjacent_wait(bot)
            ct.build_sentinel(ring_position, site.sentinel_direction)
            bot.assault_last_progress_round = ct.get_current_round()
            return True
        if _tile_has_friendly_sentinel_now(ct, ring_position):
            _clear_adjacent_wait(bot)
            return False
        if _tile_has_other_builder_now(ct, ring_position):
            _clear_adjacent_wait(bot)
            return False
        if _should_hold_adjacent_wait(bot, ct, site):
            bot.assault_subrole = "wait_adjacent"
            return True
        _clear_adjacent_wait(bot)
        return False

    _clear_adjacent_wait(bot)
    _move_toward(bot, ct, ring_position, allow_enemy_builder_at_target=True)
    return True


def _execute_support(
    bot,
    ct: Controller,
    *,
    anchor: Position,
    site: assault.AssaultSite | None = None,
    forbidden_position: Position | None = None,
) -> bool:
    current_pos = ct.get_position()
    assessment = _anchor_assessment(bot, ct, anchor)
    bot.assault_anchor_status = assessment.status
    if assessment.status != assault.ANCHOR_LIVE:
        return False

    if _is_harassable_enemy_building(bot, ct, current_pos) and ct.can_fire(current_pos):
        ct.fire(current_pos)
        bot.assault_last_progress_round = ct.get_current_round()
        return True

    target = assault.choose_support_harassment_target(
        anchor=anchor,
        enemies=_assault_enemies(bot),
        current_position=current_pos,
    )
    if target is not None and forbidden_position is not None and target == forbidden_position:
        target = None

    if target is not None:
        _move_toward(bot, ct, target, allow_enemy_builder_at_target=True)
        return True

    if site is not None:
        if site.marginal_value <= 0:
            return False
        orbit_target = assault.spread_sweep_target(
            anchor=anchor,
            spawn_slot=bot.spawn_slot,
            map_width=ct.get_map_width(),
            map_height=ct.get_map_height(),
            recently_visited=set(bot.recent_assault_waypoints),
            blocked_positions={
                (site.ring_position.x, site.ring_position.y),
            },
        )
        _move_toward(bot, ct, orbit_target)
        return True

    if ct.get_position().distance_squared(anchor) > ASSAULT_LOCAL_STALL_RADIUS_SQ:
        _move_toward(bot, ct, anchor)
        return True
    return False


def _choose_scout_target(
    bot,
    ct: Controller,
    *,
    live_anchor: Position | None,
) -> Position | None:
    current_round = ct.get_current_round()
    cached_target = _cached_scout_target(bot, ct)
    if cached_target is not None:
        bot.logger.log(f"reusing scout target {cached_target}")
        return cached_target

    anchor = None
    if live_anchor is not None:
        anchor = live_anchor
    elif bot.predicted_enemy_harvesters:
        predicted_enemy_harvesters = [
            candidate
            for candidate in bot.predicted_enemy_harvesters
            if not _is_anchor_blacklisted(bot, candidate.position, current_round)
            and not _is_locally_claimed_assault_anchor(bot, candidate.position)
            and not _is_in_exhausted_region(
                bot, candidate.position, current_round
            )
        ]
        if _use_frontier_scouting(ct):
            predicted_frontier = {
                candidate.position: _anchor_frontier_metrics(bot, ct, candidate.position)
                for candidate in predicted_enemy_harvesters
            }
            predicted_sector_penalty = {
                candidate.position: int(
                    _is_in_exhausted_sector(
                        bot,
                        ct,
                        candidate.position,
                        current_round,
                    )
                )
                for candidate in predicted_enemy_harvesters
            }
            predicted_enemy_harvesters.sort(
                key=lambda candidate: (
                    -predicted_frontier[candidate.position][0],
                    -predicted_frontier[candidate.position][1],
                    predicted_sector_penalty[candidate.position],
                    candidate.source_rank,
                    0 if candidate.mode == bot.best_symmetry_mode else 1,
                    0 if not candidate.same_lane else 1,
                    candidate.travel_distance,
                    candidate.position.x,
                    candidate.position.y,
                )
            )
        else:
            predicted_enemy_harvesters.sort(
                key=lambda candidate: (
                    0 if not candidate.same_lane else 1,
                    candidate.source_rank,
                    candidate.travel_distance,
                    candidate.position.x,
                    candidate.position.y,
                )
            )
        anchor = assault.choose_predicted_scout_anchor(
            predicted_enemy_harvesters=predicted_enemy_harvesters,
            spawn_slot=bot.spawn_slot,
            current_round=ct.get_current_round(),
        )
    elif bot.enemy_core_anchor is not None:
        anchor = bot.enemy_core_anchor
    elif bot.core_pos is not None:
        surviving = tuple(bot.symmetry_candidates) or assault.SYMMETRY_MODES
        if surviving:
            epoch = (ct.get_current_round() // 10) % len(surviving)
            slot = 0 if bot.spawn_slot is None else bot.spawn_slot
            chosen_mode = surviving[(slot + epoch) % len(surviving)]
            anchor = assault.mirror_position(
                bot.core_pos,
                chosen_mode,
                map_width=ct.get_map_width(),
                map_height=ct.get_map_height(),
            )

    if anchor is None:
        target = _select_global_enemy_frontier_target(bot, ct, anchor_hint=None)
        if target is None:
            return None
        _remember_scout_target(bot, ct, target, anchor=None)
        bot.logger.log(f"global scout target {target}")
        return target

    if _use_frontier_scouting(ct):
        target = _select_scout_frontier_target(bot, ct, anchor)
    else:
        target = assault.spread_sweep_target(
            anchor=anchor,
            spawn_slot=bot.spawn_slot,
            map_width=ct.get_map_width(),
            map_height=ct.get_map_height(),
            recently_visited=set(bot.recent_assault_waypoints),
            blocked_positions=set(bot.pathfinding_state["known_obstacles"]),
        )
    if target is None:
        target = _select_global_enemy_frontier_target(bot, ct, anchor_hint=anchor)
        if target is None:
            return None
        _remember_scout_target(bot, ct, target, anchor=anchor)
        bot.logger.log(f"fallback scout target {target} from {anchor}")
    else:
        _remember_scout_target(bot, ct, target, anchor=anchor)
    bot.recent_assault_waypoints[(target.x, target.y)] = current_round
    return target


def _scout_chunk_radius(ct: Controller) -> int:
    max_dim = max(ct.get_map_width(), ct.get_map_height())
    if max_dim <= 20:
        return 1
    if max_dim <= 32:
        return 2
    return 3


def _chunk_key(position: Position) -> tuple[int, int]:
    return (position.x // perception.CHUNK_SIZE, position.y // perception.CHUNK_SIZE)


def _chunk_center(
    chunk: tuple[int, int],
    *,
    map_width: int,
    map_height: int,
) -> Position:
    return Position(
        min(
            map_width - 1,
            chunk[0] * perception.CHUNK_SIZE + perception.CHUNK_SIZE // 2,
        ),
        min(
            map_height - 1,
            chunk[1] * perception.CHUNK_SIZE + perception.CHUNK_SIZE // 2,
        ),
    )


def _chunk_last_seen(
    bot,
    chunk: tuple[int, int],
    *,
    current_round: int,
) -> tuple[int, int]:
    last_seen = getattr(bot, "explored_chunk_last_seen", {}).get(chunk)
    if last_seen is None:
        return 1, ASSAULT_SCOUT_CHUNK_STALE_CAP
    return 0, min(current_round - last_seen, ASSAULT_SCOUT_CHUNK_STALE_CAP)


def _anchor_frontier_metrics(
    bot,
    ct: Controller,
    anchor: Position,
) -> tuple[int, int]:
    chunk_cols = (ct.get_map_width() + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
    chunk_rows = (ct.get_map_height() + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
    anchor_chunk = _chunk_key(anchor)
    unseen_chunks = 0
    stale_score = 0
    current_round = ct.get_current_round()

    for dx in range(-_scout_chunk_radius(ct), _scout_chunk_radius(ct) + 1):
        for dy in range(-_scout_chunk_radius(ct), _scout_chunk_radius(ct) + 1):
            chunk = (anchor_chunk[0] + dx, anchor_chunk[1] + dy)
            if not (0 <= chunk[0] < chunk_cols and 0 <= chunk[1] < chunk_rows):
                continue
            unseen, stale = _chunk_last_seen(bot, chunk, current_round=current_round)
            unseen_chunks += unseen
            stale_score += stale

    return unseen_chunks, stale_score


def _is_viable_scout_staging_tile(
    bot,
    ct: Controller,
    position: Position,
) -> bool:
    if not utils.in_bounds(ct, position):
        return False

    data = bot.grid.get((position.x, position.y))
    if data is None or data.get("env") is None:
        return True

    if data.get("env") != Environment.EMPTY:
        return False

    entity = data.get("entity")
    entity_team = data.get("entity_team")
    if entity == EntityType.HARVESTER:
        return False
    if entity == EntityType.CORE and entity_team != ct.get_team():
        return False
    if (
        entity == EntityType.BUILDER_BOT
        and entity_team == ct.get_team()
        and position != ct.get_position()
    ):
        return False
    if entity is not None and entity not in {EntityType.BUILDER_BOT}:
        return False

    building = data.get("building")
    building_team = data.get("building_team")
    if building is None or building in {
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.MARKER,
    }:
        return True
    return building == EntityType.CORE and building_team == ct.get_team()


def _normalize_scout_target(
    bot,
    ct: Controller,
    target: Position,
) -> Position | None:
    if _is_viable_scout_staging_tile(bot, ct, target):
        return target

    current_pos = ct.get_position()
    best: tuple[tuple[int, int, int, int], Position] | None = None
    for radius in (1, 2):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                candidate = Position(target.x + dx, target.y + dy)
                if not _is_viable_scout_staging_tile(bot, ct, candidate):
                    continue
                score = (
                    abs(dx) + abs(dy),
                    assault.manhattan(current_pos, candidate),
                    candidate.x,
                    candidate.y,
                )
                if best is None or score < best[0]:
                    best = (score, candidate)
        if best is not None:
            return best[1]
    return None


def _remember_scout_target(
    bot,
    ct: Controller,
    target: Position,
    *,
    anchor: Position | None,
) -> None:
    bot.assault_scout_state = {
        "target": (target.x, target.y),
        "chunk": _chunk_key(target),
        "anchor": None if anchor is None else (anchor.x, anchor.y),
        "expires_round": ct.get_current_round() + ASSAULT_SCOUT_TARGET_TTL,
    }


def _cached_scout_target(
    bot,
    ct: Controller,
) -> Position | None:
    scout_state = getattr(bot, "assault_scout_state", {})
    current_round = ct.get_current_round()
    target_key = scout_state.get("target")
    if target_key is None:
        return None
    if scout_state.get("expires_round", -1) < current_round:
        _clear_scout_state(bot)
        return None

    target = Position(target_key[0], target_key[1])
    normalized_target = _normalize_scout_target(bot, ct, target)
    if normalized_target is None:
        _clear_scout_state(bot)
        return None

    chunk = scout_state.get("chunk") or _chunk_key(normalized_target)
    if ct.get_position().distance_squared(normalized_target) <= ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ:
        if ct.get_position() != normalized_target:
            return normalized_target
        unseen, stale = _chunk_last_seen(bot, chunk, current_round=current_round)
        if unseen == 0 and stale <= 1:
            _clear_scout_state(bot)
            return None

    if normalized_target != target:
        anchor_key = scout_state.get("anchor")
        anchor = None if anchor_key is None else Position(anchor_key[0], anchor_key[1])
        _remember_scout_target(bot, ct, normalized_target, anchor=anchor)
    return normalized_target


def _enemy_half_metrics(
    bot,
    center: Position,
    *,
    anchor_hint: Position | None,
) -> tuple[int, int]:
    if bot.core_pos is None or anchor_hint is None:
        return 0, 0

    axis_dx = anchor_hint.x - bot.core_pos.x
    axis_dy = anchor_hint.y - bot.core_pos.y
    rel_dx = center.x - bot.core_pos.x
    rel_dy = center.y - bot.core_pos.y
    forward = (rel_dx * axis_dx) + (rel_dy * axis_dy)
    enemy_side = int(
        center.distance_squared(anchor_hint) < center.distance_squared(bot.core_pos)
    )
    return enemy_side, forward


def _is_interesting_frontier_chunk(unseen: int, stale: int) -> bool:
    return unseen > 0 or stale >= ASSAULT_GLOBAL_FRONTIER_STALE_MIN


def _select_global_enemy_frontier_target(
    bot,
    ct: Controller,
    *,
    anchor_hint: Position | None,
) -> Position | None:
    current_pos = ct.get_position()
    current_round = ct.get_current_round()
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    chunk_cols = (map_width + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
    chunk_rows = (map_height + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
    current_chunk = _chunk_key(current_pos)
    recent_waypoints = getattr(bot, "recent_assault_waypoints", {})
    blocked_positions = set(bot.pathfinding_state["known_obstacles"])
    candidates: list[tuple[tuple[int, int, int, int, int, int, int, int, int], Position]] = []
    seen_positions: set[tuple[int, int]] = set()

    for chunk_x in range(chunk_cols):
        for chunk_y in range(chunk_rows):
            chunk = (chunk_x, chunk_y)
            raw_target = _chunk_center(
                chunk,
                map_width=map_width,
                map_height=map_height,
            )
            target = _normalize_scout_target(bot, ct, raw_target)
            if target is None:
                continue
            key = (target.x, target.y)
            if key in blocked_positions or key in seen_positions:
                continue
            if _is_in_exhausted_region(bot, target, current_round):
                continue
            seen_positions.add(key)
            unseen, stale = _chunk_last_seen(bot, chunk, current_round=current_round)
            enemy_side, forward = _enemy_half_metrics(
                bot,
                raw_target,
                anchor_hint=anchor_hint or bot.enemy_core_anchor,
            )
            interesting = _is_interesting_frontier_chunk(unseen, stale)
            if enemy_side and interesting:
                pool_rank = 0
            elif enemy_side:
                pool_rank = 1
            elif interesting:
                pool_rank = 2
            else:
                pool_rank = 3
            local_chunk_penalty = int(
                max(
                    abs(chunk[0] - current_chunk[0]),
                    abs(chunk[1] - current_chunk[1]),
                )
                <= 1
            )
            candidates.append(
                (
                    (
                        pool_rank,
                        0 if current_pos.distance_squared(target) > ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ else 1,
                        0 if unseen > 0 else 1,
                        -stale,
                        local_chunk_penalty,
                        0 if key not in recent_waypoints else 1,
                        -forward,
                        assault.manhattan(current_pos, target),
                        target.x + (target.y * map_width),
                    ),
                    target,
                )
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _select_scout_frontier_target(
    bot,
    ct: Controller,
    anchor: Position,
) -> Position | None:
    current_pos = ct.get_position()
    current_round = ct.get_current_round()
    map_width = ct.get_map_width()
    map_height = ct.get_map_height()
    chunk_cols = (map_width + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
    chunk_rows = (map_height + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE
    anchor_chunk = _chunk_key(anchor)
    desired_dx = anchor.x - current_pos.x
    desired_dy = anchor.y - current_pos.y
    recent_waypoints = getattr(bot, "recent_assault_waypoints", {})
    blocked_positions = set(bot.pathfinding_state["known_obstacles"])
    candidates: list[tuple[tuple[int, int, int, int, int, int, int, int, int], Position]] = []
    seen_positions: set[tuple[int, int]] = set()

    for dx in range(-_scout_chunk_radius(ct), _scout_chunk_radius(ct) + 1):
        for dy in range(-_scout_chunk_radius(ct), _scout_chunk_radius(ct) + 1):
            chunk = (anchor_chunk[0] + dx, anchor_chunk[1] + dy)
            if not (0 <= chunk[0] < chunk_cols and 0 <= chunk[1] < chunk_rows):
                continue
            raw_target = _chunk_center(
                chunk,
                map_width=map_width,
                map_height=map_height,
            )
            target = _normalize_scout_target(bot, ct, raw_target)
            if target is None:
                continue
            key = (target.x, target.y)
            if key in seen_positions or key in blocked_positions:
                continue
            seen_positions.add(key)
            unseen, stale = _chunk_last_seen(bot, chunk, current_round=current_round)
            outward = max(
                0,
                ((target.x - anchor.x) * desired_dx) + ((target.y - anchor.y) * desired_dy),
            )
            exhausted_penalty = int(
                _is_in_exhausted_sector(bot, ct, target, current_round)
            )
            candidates.append(
                (
                    (
                        0 if current_pos.distance_squared(target) > ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ else 1,
                        0 if unseen > 0 else 1,
                        -stale,
                        0 if key not in recent_waypoints else 1,
                        exhausted_penalty,
                        -outward,
                        abs(dx) + abs(dy),
                        assault.manhattan(current_pos, target),
                        target.x + (target.y * map_width),
                    ),
                    target,
                )
            )

    legacy_target = _normalize_scout_target(
        bot,
        ct,
        assault.spread_sweep_target(
            anchor=anchor,
            spawn_slot=bot.spawn_slot,
            map_width=map_width,
            map_height=map_height,
            recently_visited=set(recent_waypoints),
            blocked_positions=blocked_positions,
        ),
    )
    if legacy_target is not None:
        key = (legacy_target.x, legacy_target.y)
        if key not in seen_positions:
            exhausted_penalty = int(
                _is_in_exhausted_sector(bot, ct, legacy_target, current_round)
            )
            candidates.append(
                (
                    (
                        0 if current_pos.distance_squared(legacy_target) > ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ else 1,
                        1,
                        0,
                        0 if key not in recent_waypoints else 1,
                        exhausted_penalty,
                        0,
                        99,
                        assault.manhattan(current_pos, legacy_target),
                        legacy_target.x + (legacy_target.y * map_width),
                    ),
                    legacy_target,
                )
            )

    normalized_anchor = _normalize_scout_target(bot, ct, anchor)
    if normalized_anchor is not None:
        key = (normalized_anchor.x, normalized_anchor.y)
        if key not in seen_positions:
            exhausted_penalty = int(
                _is_in_exhausted_sector(bot, ct, normalized_anchor, current_round)
            )
            candidates.append(
                (
                    (
                        0 if current_pos.distance_squared(normalized_anchor) > ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ else 1,
                        1,
                        0,
                        0 if key not in recent_waypoints else 1,
                        exhausted_penalty,
                        0,
                        100,
                        assault.manhattan(current_pos, normalized_anchor),
                        normalized_anchor.x + (normalized_anchor.y * map_width),
                    ),
                    normalized_anchor,
                )
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def execute(bot, ct: Controller):
    enemies = _assault_enemies(bot)
    _refresh_anchor_blacklist(bot, ct.get_current_round())
    _refresh_exhausted_regions(bot, ct.get_current_round())
    _refresh_exhausted_sectors(bot, ct.get_current_round())
    _update_enemy_inference(bot, ct)
    live_anchor = _committed_anchor(bot, ct, enemies)
    if live_anchor is not None and _is_locally_claimed_assault_anchor(bot, live_anchor):
        _clear_anchor(bot)
        live_anchor = None
    live_assessment = None
    if live_anchor is not None:
        live_assessment = _anchor_assessment(bot, ct, live_anchor, enemies=enemies)
        bot.assault_anchor_status = live_assessment.status
        if live_assessment.status != assault.ANCHOR_LIVE:
            _retire_anchor(bot, ct, live_anchor, reason=live_assessment.status)
            live_anchor = None
    else:
        bot.assault_anchor_status = None

    chosen_site = None
    if live_anchor is not None:
        chosen_site = _best_site_for_anchor(bot, ct, live_anchor)
    if chosen_site is None:
        chosen_site = _best_visible_site(bot, ct, live_anchor)

    if chosen_site is not None:
        _publish_assault_claim(bot, ct, chosen_site.harvester_position)
        _clear_scout_state(bot)
        previous_anchor = bot.harvester_anchor
        bot.harvester_anchor = chosen_site.harvester_position
        bot.harvester_anchor_last_seen_round = ct.get_current_round()
        chosen_assessment = live_assessment
        if (
            chosen_assessment is None
            or chosen_site.harvester_position != live_anchor
        ):
            chosen_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
            )
        site_signature = _site_signature(chosen_site)
        if site_signature != getattr(bot, "assault_last_site_signature", None):
            _clear_adjacent_wait(bot)
            bot.assault_last_site_signature = site_signature
            if (
                previous_anchor != chosen_site.harvester_position
                or chosen_assessment is None
                or not chosen_assessment.pressure_established
                or chosen_site.has_high_value_target
                or chosen_site.uncovered_logistics_gain >= 2
            ):
                bot.assault_last_progress_round = ct.get_current_round()
        bot.assault_subrole = "build_now"
        if _execute_site(bot, ct, chosen_site):
            if _is_locally_stalled_for_site(
                bot,
                ct,
                chosen_site.harvester_position,
                site=chosen_site,
            ):
                _retire_anchor(bot, ct, chosen_site.harvester_position, reason="local stall")
            return

        if _is_locally_stalled_for_site(
            bot,
            ct,
            chosen_site.harvester_position,
            site=chosen_site,
        ):
            _retire_anchor(bot, ct, chosen_site.harvester_position, reason="local stall")
            live_anchor = None
        else:
            bot.assault_subrole = "harass"
            if _execute_support(
                bot,
                ct,
                anchor=chosen_site.harvester_position,
                site=chosen_site,
                forbidden_position=chosen_site.ring_position,
            ):
                return
            post_support_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
            )
            if post_support_assessment.status != assault.ANCHOR_LIVE:
                _retire_anchor(
                    bot,
                    ct,
                    chosen_site.harvester_position,
                    reason=post_support_assessment.status,
                )
            else:
                _retire_anchor(
                    bot,
                    ct,
                    chosen_site.harvester_position,
                    reason="no_new_value",
                )
            live_anchor = None

    if live_anchor is not None:
        _publish_assault_claim(bot, ct, live_anchor)
        _clear_scout_state(bot)
        bot.assault_subrole = "support"
        if _is_locally_stalled(bot, ct, live_anchor):
            _retire_anchor(bot, ct, live_anchor, reason="support stall")
            live_anchor = None
        else:
            if _execute_support(bot, ct, anchor=live_anchor):
                return
            post_support_assessment = _anchor_assessment(
                bot,
                ct,
                live_anchor,
                enemies=enemies,
            )
            if post_support_assessment.status != assault.ANCHOR_LIVE:
                _retire_anchor(bot, ct, live_anchor, reason=post_support_assessment.status)
            else:
                _retire_anchor(bot, ct, live_anchor, reason="support exhausted")
            live_anchor = None

    scout_target = _choose_scout_target(bot, ct, live_anchor=live_anchor)
    if scout_target is not None:
        bot.assault_subrole = "scout"
        _move_toward(bot, ct, scout_target, build_road=True)
