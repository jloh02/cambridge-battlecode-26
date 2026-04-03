from __future__ import annotations

from cambc import Controller, Direction, EntityType, Position

import assault
import navigation
import utils


ASSAULT_OBJECTIVE_TTL = 16
ASSAULT_RECENT_CONFIRM_TTL = 16
ASSAULT_STALL_TTL = 10
ASSAULT_BLACKLIST_TTL = 28
ASSAULT_LOCAL_STALL_RADIUS_SQ = 49
RECENT_WAYPOINT_TTL = 12


def _clear_anchor(bot) -> None:
    bot.harvester_anchor = None
    bot.harvester_anchor_last_seen_round = -9999
    bot.assault_anchor_status = None
    bot.assault_last_site_signature = None
    bot.assault_subrole = "support"


def _refresh_anchor_blacklist(bot, current_round: int) -> None:
    anchor_blacklist = getattr(bot, "assault_anchor_blacklist", {})
    bot.assault_anchor_blacklist = {
        key: expiry_round
        for key, expiry_round in anchor_blacklist.items()
        if expiry_round > current_round
    }


def _is_anchor_blacklisted(bot, position: Position, current_round: int) -> bool:
    return (
        getattr(bot, "assault_anchor_blacklist", {}).get((position.x, position.y), -1)
        > current_round
    )


def _blacklist_anchor(bot, position: Position, current_round: int) -> None:
    if not hasattr(bot, "assault_anchor_blacklist"):
        bot.assault_anchor_blacklist = {}
    bot.assault_anchor_blacklist[(position.x, position.y)] = (
        current_round + ASSAULT_BLACKLIST_TTL
    )


def _retire_anchor(bot, ct: Controller, position: Position, *, reason: str) -> None:
    bot.logger.log(f"retiring anchor {position} because {reason}")
    _blacklist_anchor(bot, position, ct.get_current_round())
    _clear_anchor(bot)


def _anchor_assessment(
    bot,
    ct: Controller,
    anchor: Position,
    *,
    enemies: list[assault.VisibleEnemy] | None = None,
) -> assault.AnchorAssessment:
    return assault.assess_anchor(
        harvester_position=anchor,
        current_position=ct.get_position(),
        enemies=_assault_enemies(bot) if enemies is None else enemies,
        grid=bot.grid,
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct)
        | _visible_friendly_ring_sentinels(bot, ct, anchor),
        legal_fire_fn=_legal_fire_fn(ct),
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
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
    ignored_harvesters: set[Position] = set()
    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        if _is_anchor_blacklisted(bot, enemy.position, current_round):
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
    allow_enemy_builder_at_target: bool = False,
) -> None:
    bot.logger.log(f"assault moving toward {target}")
    if navigation.move_towards(
        bot,
        ct,
        target,
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
                ct.move(move_dir)
                bot.assault_last_progress_round = ct.get_current_round()
                return True
        return False

    if max(abs(current_pos.x - ring_position.x), abs(current_pos.y - ring_position.y)) <= 1:
        if _is_clearable_enemy_conveyor(bot, ct, ring_position):
            _move_toward(bot, ct, ring_position, allow_enemy_builder_at_target=True)
            return True
        if ct.can_build_sentinel(ring_position, site.sentinel_direction):
            ct.build_sentinel(ring_position, site.sentinel_direction)
            bot.assault_last_progress_round = ct.get_current_round()
            return True
        if _tile_has_friendly_sentinel_now(ct, ring_position):
            return False
        if _tile_has_other_builder_now(ct, ring_position):
            return False

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
    anchor = None
    if live_anchor is not None:
        anchor = live_anchor
    elif bot.predicted_enemy_harvesters:
        predicted_enemy_harvesters = [
            candidate
            for candidate in bot.predicted_enemy_harvesters
            if not _is_anchor_blacklisted(bot, candidate.position, ct.get_current_round())
        ]
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
        return None

    target = assault.spread_sweep_target(
        anchor=anchor,
        spawn_slot=bot.spawn_slot,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        recently_visited=set(bot.recent_assault_waypoints),
        blocked_positions=set(bot.pathfinding_state["known_obstacles"]),
    )
    bot.recent_assault_waypoints[(target.x, target.y)] = ct.get_current_round()
    return target


def execute(bot, ct: Controller):
    enemies = _assault_enemies(bot)
    _refresh_anchor_blacklist(bot, ct.get_current_round())
    _update_enemy_inference(bot, ct)
    live_anchor = _committed_anchor(bot, ct, enemies)
    if live_anchor is not None:
        assessment = _anchor_assessment(bot, ct, live_anchor, enemies=enemies)
        bot.assault_anchor_status = assessment.status
        if assessment.status != assault.ANCHOR_LIVE:
            _retire_anchor(bot, ct, live_anchor, reason=assessment.status.lower())
            live_anchor = None
    else:
        bot.assault_anchor_status = None

    chosen_site = None
    if live_anchor is not None:
        chosen_site = _best_site_for_anchor(bot, ct, live_anchor)
    if chosen_site is None:
        chosen_site = _best_visible_site(bot, ct, live_anchor)

    if chosen_site is not None:
        bot.harvester_anchor = chosen_site.harvester_position
        bot.harvester_anchor_last_seen_round = ct.get_current_round()
        site_signature = _site_signature(chosen_site)
        if site_signature != getattr(bot, "assault_last_site_signature", None):
            bot.assault_last_site_signature = site_signature
            bot.assault_last_progress_round = ct.get_current_round()
        bot.assault_subrole = "build_now"
        if _execute_site(bot, ct, chosen_site):
            if _is_locally_stalled(bot, ct, chosen_site.harvester_position):
                _retire_anchor(bot, ct, chosen_site.harvester_position, reason="local stall")
            return

        if _is_locally_stalled(bot, ct, chosen_site.harvester_position):
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
            _retire_anchor(bot, ct, chosen_site.harvester_position, reason="no_new_value")
            live_anchor = None

    if live_anchor is not None:
        bot.assault_subrole = "support"
        if _is_locally_stalled(bot, ct, live_anchor):
            _retire_anchor(bot, ct, live_anchor, reason="support stall")
            live_anchor = None
        else:
            if _execute_support(bot, ct, anchor=live_anchor):
                return
            _retire_anchor(bot, ct, live_anchor, reason="support exhausted")
            live_anchor = None

    scout_target = _choose_scout_target(bot, ct, live_anchor=live_anchor)
    if scout_target is not None:
        bot.assault_subrole = "scout"
        _move_toward(bot, ct, scout_target)
