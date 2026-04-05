from __future__ import annotations

from collections import deque

from cambc import Controller, Direction, EntityType, Environment, Position

import assault
import marker
import navigation
import perception
import utils


ASSAULT_OBJECTIVE_TTL = 16
ASSAULT_RECENT_CONFIRM_TTL = 16
ASSAULT_BLACKLIST_TTL = 28
ASSAULT_GOOD_ENOUGH_TTL = 12
ASSAULT_SITE_COMMIT_TTL = 10
ASSAULT_SCOUT_CHUNK_STALE_CAP = 24
ASSAULT_SCOUT_MIN_TARGET_DISTANCE_SQ = 4
ASSAULT_SCOUT_TARGET_TTL = 18
ASSAULT_CLAIM_REFRESH_INTERVAL = 4
ASSAULT_OPENING_SHELL_CHEBYSHEV = 3
ASSAULT_CLAIM_TTL = ASSAULT_CLAIM_REFRESH_INTERVAL * 3
RECENT_WAYPOINT_TTL = 12
ASSAULT_GLOBAL_FRONTIER_STALE_MIN = max(2, perception.CHUNK_SIZE)
NAV_FAILURE_LIMIT = 8
PROGRESS_STALL_LIMIT = 40
WAIT_FOR_SLOT_TTL = 5
BUILD_WINDOW_WAIT_TTL = 5
FIRE_WAIT_TTL = 5
DISCOVERY_STALE_THRESHOLD = 20
ASSAULT_BOOTSTRAP_ROUTE_TTL = 8
BOOTSTRAP_MAX_TURNS = 14
BOOTSTRAP_BACKSTEP_AFTER = 2
BOOTSTRAP_LOCAL_REROUTE_AFTER = 4
BOOTSTRAP_LOCAL_REROUTE_MAX_TILES = 20
NO_ACTIONABLE_SITE_REASON = "NO_ACTIONABLE_SITE"


def _clear_scout_state(bot) -> None:
    bot.assault_scout_state = {
        "target": None,
        "chunk": None,
        "anchor": None,
        "expires_round": -1,
    }


def _clear_bootstrap_state(bot) -> None:
    bot.assault_bootstrap_state = {
        "target": None,
        "path": [],
        "expires_round": -1,
        "blocked_turns": 0,
        "start_round": -1,
        "last_position": None,
        "checkpoint_chunk": None,
    }


def _clear_bootstrap_route(bot) -> None:
    state = getattr(bot, "assault_bootstrap_state", None)
    if not isinstance(state, dict):
        _clear_bootstrap_state(bot)
        return
    state["target"] = None
    state["path"] = []
    state["expires_round"] = -1


def _clear_execute_state(bot) -> None:
    bot.assault_execute_state = {
        "subplan": None,
        "anchor": None,
        "ring": None,
        "direction": None,
        "wait_turns": 0,
        "fire_wait_turns": 0,
    }


def _reset_nav_progress(bot) -> None:
    bot.assault_nav_failure_count = 0
    bot.assault_progress_stall_count = 0
    bot.assault_best_dist_to_ring = 9999
    bot.assault_nav_progress_target = None


def _clear_committed_site(bot) -> None:
    bot.assault_committed_site = None
    bot.assault_committed_site_round = -9999
    _clear_execute_state(bot)
    _reset_nav_progress(bot)


def _clear_anchor(bot) -> None:
    bot.harvester_anchor = None
    bot.harvester_anchor_last_seen_round = -9999
    bot.assault_anchor_status = None
    bot.assault_last_site_signature = None
    bot.assault_subrole = "scout"
    _clear_committed_site(bot)


def _spawn_shell_vector(bot) -> tuple[int, int] | None:
    if bot.core_pos is None:
        return None

    if bot.spawn_pos is not None:
        dx = bot.spawn_pos.x - bot.core_pos.x
        dy = bot.spawn_pos.y - bot.core_pos.y
        if dx != 0 or dy != 0:
            return (
                1 if dx > 0 else -1 if dx < 0 else 0,
                1 if dy > 0 else -1 if dy < 0 else 0,
            )

    slot_vectors = {
        0: (1, -1),
        1: (-1, -1),
        2: (1, 1),
        3: (-1, 1),
    }
    return slot_vectors.get(bot.spawn_slot)


def _in_spawn_shell(
    bot,
    ct: Controller,
    *,
    position: Position | None = None,
) -> bool:
    if bot.core_pos is None:
        return False
    pos = ct.get_position() if position is None else position
    return (
        max(abs(pos.x - bot.core_pos.x), abs(pos.y - bot.core_pos.y))
        <= ASSAULT_OPENING_SHELL_CHEBYSHEV
    )


def _ensure_bootstrap_state(bot, ct: Controller) -> None:
    state = getattr(bot, "assault_bootstrap_state", None)
    if not isinstance(state, dict):
        _clear_bootstrap_state(bot)
        state = bot.assault_bootstrap_state
    if state.get("start_round", -1) < 0:
        state["start_round"] = ct.get_current_round()


def bootstrap_egress_active(bot, ct: Controller) -> bool:
    return (
        bool(getattr(bot, "is_assault_role", False))
        and not getattr(bot, "assault_opening_escape_complete", False)
    )


def opening_escape_active(bot, ct: Controller) -> bool:
    return bootstrap_egress_active(bot, ct)


def bootstrap_egress_skip_perception(bot, ct: Controller) -> bool:
    return bootstrap_egress_active(bot, ct) and _in_spawn_shell(bot, ct)


def _bootstrap_chunk_distance(ct: Controller) -> int:
    return 2 if max(ct.get_map_width(), ct.get_map_height()) >= 28 else 1


def _bootstrap_chunk_bounds(ct: Controller) -> tuple[int, int]:
    return (
        (ct.get_map_width() + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE,
        (ct.get_map_height() + perception.CHUNK_SIZE - 1) // perception.CHUNK_SIZE,
    )


def _bootstrap_checkpoint_chunk(bot, ct: Controller) -> tuple[int, int] | None:
    _ensure_bootstrap_state(bot, ct)
    cached = bot.assault_bootstrap_state.get("checkpoint_chunk")
    if cached is not None:
        return (cached[0], cached[1])
    outward = _spawn_shell_vector(bot)
    if outward is None or bot.core_pos is None:
        return None
    chunk_cols, chunk_rows = _bootstrap_chunk_bounds(ct)
    core_chunk = _chunk_key(bot.core_pos)
    distance = _bootstrap_chunk_distance(ct)
    checkpoint = (
        max(0, min(chunk_cols - 1, core_chunk[0] + outward[0] * distance)),
        max(0, min(chunk_rows - 1, core_chunk[1] + outward[1] * distance)),
    )
    if checkpoint == core_chunk:
        checkpoint = (
            max(0, min(chunk_cols - 1, core_chunk[0] + outward[0])),
            max(0, min(chunk_rows - 1, core_chunk[1] + outward[1])),
        )
    bot.assault_bootstrap_state["checkpoint_chunk"] = checkpoint
    return checkpoint


def _bootstrap_checkpoint_position(bot, ct: Controller) -> Position | None:
    checkpoint_chunk = _bootstrap_checkpoint_chunk(bot, ct)
    if checkpoint_chunk is None:
        return None
    return _chunk_center(
        checkpoint_chunk,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
    )


def _bootstrap_projection(bot, position: Position) -> int:
    outward = _spawn_shell_vector(bot)
    if outward is None or bot.core_pos is None:
        return 0
    dx = position.x - bot.core_pos.x
    dy = position.y - bot.core_pos.y
    return (dx * outward[0]) + (dy * outward[1])


def _bootstrap_core_chebyshev(bot, position: Position) -> int:
    if bot.core_pos is None:
        return 0
    return max(abs(position.x - bot.core_pos.x), abs(position.y - bot.core_pos.y))


def _bootstrap_progress_rank(
    bot,
    ct: Controller,
    position: Position,
) -> tuple[int, int, int, int]:
    checkpoint = _bootstrap_checkpoint_position(bot, ct) or position
    return (
        0 if not _in_spawn_shell(bot, ct, position=position) else 1,
        max(abs(position.x - checkpoint.x), abs(position.y - checkpoint.y)),
        -_bootstrap_core_chebyshev(bot, position),
        -_bootstrap_projection(bot, position),
    )


def _bootstrap_visible_ore_now(bot) -> bool:
    for position_key in getattr(bot, "visible_positions", set()):
        data = bot.grid.get(position_key, {})
        if data.get("env") in {Environment.ORE_TITANIUM, Environment.ORE_AXIONITE}:
            return True
    return False


def _bootstrap_has_signal(bot) -> bool:
    return bool(
        getattr(bot, "visible_enemy_targets", ())
        or getattr(bot, "visible_enemy_passable_buildings", ())
        or _bootstrap_visible_ore_now(bot)
    )


def _bootstrap_should_complete(bot, ct: Controller) -> bool:
    _ensure_bootstrap_state(bot, ct)
    state = bot.assault_bootstrap_state
    start_round = state.get("start_round", ct.get_current_round())
    if ct.get_current_round() - start_round >= BOOTSTRAP_MAX_TURNS:
        return True
    current_pos = ct.get_position()
    if _in_spawn_shell(bot, ct, position=current_pos):
        return False
    if _bootstrap_has_signal(bot):
        return True
    checkpoint = _bootstrap_checkpoint_position(bot, ct)
    if checkpoint is None:
        return True
    if _chunk_key(current_pos) == _bootstrap_checkpoint_chunk(bot, ct):
        return True
    return _bootstrap_projection(bot, current_pos) >= _bootstrap_projection(bot, checkpoint)


def _refresh_bootstrap_egress_state(bot, ct: Controller) -> None:
    if getattr(bot, "assault_opening_escape_complete", False):
        return
    if not bootstrap_egress_active(bot, ct):
        return
    _ensure_bootstrap_state(bot, ct)
    if not _bootstrap_should_complete(bot, ct):
        return
    bot.assault_opening_escape_complete = True
    bot.assault_subrole = "scout"
    _clear_bootstrap_state(bot)


def _refresh_opening_escape_state(bot, ct: Controller) -> None:
    _refresh_bootstrap_egress_state(bot, ct)


def _anchor_blacklist_ttl(reason: str) -> int:
    normalized_reason = _normalize_reason(reason)
    if normalized_reason == assault.ANCHOR_GOOD_ENOUGH:
        return ASSAULT_GOOD_ENOUGH_TTL
    if normalized_reason == NO_ACTIONABLE_SITE_REASON:
        return ASSAULT_CLAIM_TTL
    if normalized_reason in {"COORDINATION_YIELD", "WAIT_TIMEOUT"}:
        return ASSAULT_CLAIM_TTL
    if normalized_reason == "NAVIGATION_BLOCKED":
        return ASSAULT_CLAIM_TTL
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
    if utils.place_assault_marker_around(ct, ct.get_position(), marker_value):
        bot.assault_claim_state = {
            "anchor": anchor_key,
            "last_round": current_round,
        }


def _remember_bootstrap_route(
    bot,
    ct: Controller,
    target: Position,
    path: list[Direction],
) -> None:
    _ensure_bootstrap_state(bot, ct)
    bot.assault_bootstrap_state["target"] = (target.x, target.y)
    bot.assault_bootstrap_state["path"] = list(path)
    bot.assault_bootstrap_state["expires_round"] = (
        ct.get_current_round() + ASSAULT_BOOTSTRAP_ROUTE_TTL
    )
    bot.assault_bootstrap_state["blocked_turns"] = 0


def _remember_bootstrap_previous_position(bot, position: Position) -> None:
    bot.assault_bootstrap_state["last_position"] = (position.x, position.y)


def _cached_bootstrap_route(
    bot,
    ct: Controller,
) -> tuple[Position, list[Direction]] | None:
    if not bootstrap_egress_active(bot, ct):
        return None

    state = getattr(bot, "assault_bootstrap_state", {})
    target_key = state.get("target")
    path = list(state.get("path", []))
    if target_key is None or not path:
        return None
    if state.get("expires_round", -1) < ct.get_current_round():
        _clear_bootstrap_route(bot)
        return None

    target = Position(target_key[0], target_key[1])
    if not utils.in_bounds(ct, target):
        _clear_bootstrap_route(bot)
        return None
    return target, path


def _bootstrap_candidate_sort_key(
    bot,
    ct: Controller,
    current_pos: Position,
    candidate: Position,
    *,
    blocked_turns: int,
) -> tuple[int, int, int, int, int, int, int, int, int] | None:
    current_rank = _bootstrap_progress_rank(bot, ct, current_pos)
    candidate_rank = _bootstrap_progress_rank(bot, ct, candidate)
    chebyshev_delta = _bootstrap_core_chebyshev(bot, candidate) - _bootstrap_core_chebyshev(
        bot,
        current_pos,
    )
    projection_delta = _bootstrap_projection(bot, candidate) - _bootstrap_projection(
        bot,
        current_pos,
    )
    if current_rank[0] == 1 and candidate_rank[0] == 0:
        category = 0
    elif candidate_rank < current_rank and chebyshev_delta >= 0 and projection_delta > 0:
        category = 1
    elif candidate_rank <= current_rank and chebyshev_delta >= 0 and projection_delta >= 0:
        category = 2
    elif blocked_turns >= BOOTSTRAP_BACKSTEP_AFTER:
        category = 3
    else:
        return None

    last_position_key = getattr(bot, "assault_bootstrap_state", {}).get("last_position")
    checkpoint_chunk = _bootstrap_checkpoint_chunk(bot, ct)
    return (
        category,
        *candidate_rank,
        1 if (candidate.x, candidate.y) == last_position_key else 0,
        0 if checkpoint_chunk is not None and _chunk_key(candidate) == checkpoint_chunk else 1,
        candidate.x,
        candidate.y,
    )


def _bootstrap_preferred_direction(bot, ct: Controller) -> Direction | None:
    current_pos = ct.get_position()
    blocked_turns = getattr(bot, "assault_bootstrap_state", {}).get("blocked_turns", 0)
    candidates: list[tuple[tuple[int, int, int, int, int, int, int, int, int], Direction]] = []
    for direction in utils.DIRECTIONS:
        if not ct.can_move(direction):
            continue
        candidate = current_pos.add(direction)
        sort_key = _bootstrap_candidate_sort_key(
            bot,
            ct,
            current_pos,
            candidate,
            blocked_turns=blocked_turns,
        )
        if sort_key is None:
            continue
        candidates.append((sort_key, direction))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _bootstrap_local_route(
    bot,
    ct: Controller,
) -> tuple[Position, list[Direction]] | None:
    checkpoint = _bootstrap_checkpoint_position(bot, ct)
    if checkpoint is None:
        return None

    current_pos = ct.get_position()
    current_rank = _bootstrap_progress_rank(bot, ct, current_pos)
    navigation._refresh_local_obstacle_memory(
        bot,
        current_pos,
        bot.pathfinding_state["known_obstacles"],
        ct.get_team(),
    )
    start_key = (current_pos.x, current_pos.y)
    checkpoint_key = (checkpoint.x, checkpoint.y)
    queue = deque([start_key])
    parents: dict[tuple[int, int], tuple[tuple[int, int], Direction] | None] = {
        start_key: None
    }
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()
    my_team = ct.get_team()
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    nodes_expanded = 0

    while queue and nodes_expanded < BOOTSTRAP_LOCAL_REROUTE_MAX_TILES:
        current_key = queue.popleft()
        current = Position(current_key[0], current_key[1])
        nodes_expanded += 1

        if current_key != start_key and _bootstrap_progress_rank(bot, ct, current) < current_rank:
            action_path = navigation._reconstruct_assault_path(
                start_key,
                current_key,
                parents,
            )
            return current, [direction for _action_type, direction in action_path]

        ordered_directions = sorted(
            utils.DIRECTIONS,
            key=lambda direction: _bootstrap_candidate_sort_key(
                bot,
                ct,
                current,
                current.add(direction),
                blocked_turns=BOOTSTRAP_LOCAL_REROUTE_AFTER,
            )
            or (9, 9, 9, 9, 9, 9, 9, 9, 9),
        )
        for direction in ordered_directions:
            next_pos = current.add(direction)
            next_key = (next_pos.x, next_pos.y)
            if next_key in parents:
                continue
            if max(abs(next_pos.x - current_pos.x), abs(next_pos.y - current_pos.y)) > 3:
                continue
            if current_key == start_key and not ct.can_move(direction):
                continue
            if not navigation._assault_is_walkable_key(
                bot.grid,
                known_obstacles,
                next_key,
                checkpoint_key,
                map_w=map_w,
                map_h=map_h,
                my_team=my_team,
                allow_enemy_builder_at_target=False,
                temporary_obstacles={},
            ):
                continue
            parents[next_key] = (current_key, direction)
            queue.append(next_key)

    return None


def _bootstrap_egress_step(bot, ct: Controller) -> bool:
    _ensure_bootstrap_state(bot, ct)
    current_pos = ct.get_position()

    cached_route = _cached_bootstrap_route(bot, ct)
    if cached_route is not None:
        _target, path = cached_route
        move_dir = path[0]
        if ct.can_move(move_dir):
            _remember_bootstrap_previous_position(bot, current_pos)
            ct.move(move_dir)
            bot.assault_bootstrap_state["path"] = path[1:]
            if not bot.assault_bootstrap_state["path"]:
                _clear_bootstrap_route(bot)
            bot.assault_bootstrap_state["blocked_turns"] = 0
            utils.bump_profile(bot, "assault_bootstrap_moves")
            bot.assault_last_progress_round = ct.get_current_round()
            return True
        _clear_bootstrap_route(bot)

    preferred = _bootstrap_preferred_direction(bot, ct)
    if preferred is not None:
        _remember_bootstrap_previous_position(bot, current_pos)
        ct.move(preferred)
        bot.assault_bootstrap_state["blocked_turns"] = 0
        utils.bump_profile(bot, "assault_bootstrap_moves")
        bot.assault_last_progress_round = ct.get_current_round()
        return True

    blocked_turns = bot.assault_bootstrap_state.get("blocked_turns", 0) + 1
    bot.assault_bootstrap_state["blocked_turns"] = blocked_turns
    if blocked_turns < BOOTSTRAP_LOCAL_REROUTE_AFTER:
        return True

    route = _bootstrap_local_route(bot, ct)
    if route is None:
        return True

    target, path = route
    if not path:
        return True

    _remember_bootstrap_route(bot, ct, target, path)
    move_dir = path[0]
    if not ct.can_move(move_dir):
        _clear_bootstrap_route(bot)
        bot.assault_bootstrap_state["blocked_turns"] = blocked_turns
        return True

    _remember_bootstrap_previous_position(bot, current_pos)
    ct.move(move_dir)
    bot.assault_bootstrap_state["path"] = path[1:]
    if not bot.assault_bootstrap_state["path"]:
        _clear_bootstrap_route(bot)
    bot.assault_bootstrap_state["blocked_turns"] = 0
    utils.bump_profile(bot, "assault_bootstrap_moves")
    bot.assault_last_progress_round = ct.get_current_round()
    return True


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
    _mark_anchor_unavailable(bot, ct, position, reason=reason)
    committed_site = getattr(bot, "assault_committed_site", None)
    if committed_site is not None and committed_site.harvester_position == position:
        _clear_committed_site(bot)
    _clear_anchor(bot)
    _clear_scout_state(bot)


def _mark_anchor_unavailable(
    bot,
    ct: Controller,
    position: Position,
    *,
    reason: str,
) -> None:
    current_round = ct.get_current_round()
    ttl = _anchor_blacklist_ttl(reason)
    if ttl > 0:
        _blacklist_anchor(bot, position, current_round, ttl=ttl)
    if _normalize_reason(reason) not in {"COORDINATION_YIELD", "WAIT_TIMEOUT"}:
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


def _abandon_anchor_candidate(
    bot,
    ct: Controller,
    position: Position,
    *,
    reason: str,
) -> None:
    bot.logger.log(f"abandoning visible anchor {position} because {reason}")
    _mark_anchor_unavailable(bot, ct, position, reason=reason)
    committed_site = getattr(bot, "assault_committed_site", None)
    if committed_site is not None and committed_site.harvester_position == position:
        _clear_committed_site(bot)
    if getattr(bot, "harvester_anchor", None) == position:
        _clear_anchor(bot)
    scout_state = getattr(bot, "assault_scout_state", {})
    if scout_state.get("anchor") == (position.x, position.y):
        _clear_scout_state(bot)


def _anchor_assessment(
    bot,
    ct: Controller,
    anchor: Position,
    *,
    enemies: list[assault.VisibleEnemy] | None = None,
    cache: dict[tuple[int, int], assault.AnchorAssessment] | None = None,
) -> assault.AnchorAssessment:
    if cache is not None:
        cached = cache.get((anchor.x, anchor.y))
        if cached is not None:
            return cached
    current_enemies = _assault_enemies(bot) if enemies is None else enemies
    result = assault.assess_anchor(
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
        enemy_core_center=_visible_enemy_core_center(current_enemies),
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
        friendly_builder_positions=getattr(bot, "visible_friendly_builders", []),
        profile=getattr(bot, "turn_profile", None),
    )
    if cache is not None:
        cache[(anchor.x, anchor.y)] = result
    return result


def _site_signature(site: assault.AssaultSite) -> tuple[object, ...]:
    return (
        site.harvester_position.x,
        site.harvester_position.y,
        site.ring_position.x,
        site.ring_position.y,
        site.sentinel_direction.name,
    )


def _committed_plan_hint(
    bot,
) -> tuple[Position | None, Direction | None]:
    site = getattr(bot, "assault_committed_site", None)
    if site is None:
        return None, None
    return site.ring_position, site.sentinel_direction


def _legal_fire_fn(bot, ct: Controller):
    if not hasattr(ct, "can_fire_from"):
        return None

    def _legal(position: Position, direction: Direction, target: Position) -> bool:
        utils.bump_profile(bot, "assault_can_fire_from_calls")
        try:
            allowed = ct.can_fire_from(position, direction, EntityType.SENTINEL, target)
            if allowed:
                utils.bump_profile(bot, "assault_can_fire_from_true")
            return allowed
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


def _is_clearable_enemy_ring_building(bot, ct: Controller, position: Position) -> bool:
    return _is_enemy_building_on_tile(
        bot,
        ct,
        position,
        entity_types={
            EntityType.ROAD,
            EntityType.MARKER,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
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
    ordered = sorted(
        bot.titanium_locations,
        key=lambda position: (
            assault.manhattan(position, bot.core_pos or position),
            position.x,
            position.y,
        ),
    )
    return set(ordered[:6])


def _note_new_ore(bot) -> bool:
    ore_count = len(getattr(bot, "titanium_locations", ()))
    previous = getattr(bot, "assault_known_ore_count", 0)
    bot.assault_known_ore_count = ore_count
    if ore_count > previous:
        bot.discovery_turns_without_new_ore = 0
        return True
    return False


def _update_enemy_inference(bot, ct: Controller) -> None:
    current_round = ct.get_current_round()
    _refresh_recent_waypoints(bot, current_round)
    enemies = _assault_enemies(bot)

    if bot.last_enemy_core_position is not None:
        bot.enemy_core_anchor = bot.last_enemy_core_position
        bot.enemy_core_exact = True
    elif current_round - bot.last_symmetry_update_round >= 8:
        env_count = sum(1 for data in bot.grid.values() if data.get("env") is not None)
        if (
            getattr(bot, "symmetry_tile_cache", None) is None
            or getattr(bot, "symmetry_tile_cache_count", -1) != env_count
        ):
            bot.symmetry_tile_cache = assault.build_symmetry_informative_tiles(
                grid=bot.grid,
                core_pos=bot.core_pos,
            )
            bot.symmetry_tile_cache_count = env_count
        surviving, best_mode, confidence, _ = assault.evaluate_symmetry_modes(
            grid=bot.grid,
            map_width=ct.get_map_width(),
            map_height=ct.get_map_height(),
            core_pos=bot.core_pos,
            previous_modes=tuple(bot.symmetry_candidates),
            informative_tiles=getattr(bot, "symmetry_tile_cache", None),
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
    enemy_core_focus = bot.enemy_core_anchor or _visible_enemy_core_center(enemies)
    committed_ring_position, committed_direction = _committed_plan_hint(bot)
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
        enemy_core_center=enemy_core_focus,
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
        committed_ring_position=committed_ring_position,
        committed_direction=committed_direction,
        allow_exploratory_fallback=True,
        profile=getattr(bot, "turn_profile", None),
    )


def _best_visible_site(
    bot,
    ct: Controller,
    live_anchor: Position | None,
    *,
    cache: dict[tuple[int, int], assault.AnchorAssessment] | None = None,
) -> tuple[assault.AssaultSite | None, list[tuple[Position, str]]]:
    enemies = _assault_enemies(bot)
    if not enemies:
        return None, []
    enemy_core_focus = bot.enemy_core_anchor or _visible_enemy_core_center(enemies)
    committed_ring_position, committed_direction = _committed_plan_hint(bot)
    current_round = ct.get_current_round()
    best: tuple[tuple[int, ...], assault.AssaultSite] | None = None
    abandoned: list[tuple[Position, str]] = []
    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        if _is_anchor_blacklisted(bot, enemy.position, current_round) or _is_in_exhausted_region(
            bot,
            enemy.position,
            current_round,
        ):
            continue
        assessment = _anchor_assessment(bot, ct, enemy.position, enemies=enemies, cache=cache)
        if assessment.status != assault.ANCHOR_LIVE:
            abandoned.append((enemy.position, assessment.status))
            continue
        site = assault.choose_best_site_for_harvester(
            harvester_position=enemy.position,
            current_position=ct.get_position(),
            enemies=enemies,
            map_width=ct.get_map_width(),
            map_height=ct.get_map_height(),
            grid=bot.grid,
            my_team=ct.get_team(),
            actor_id=ct.get_id(),
            blocked_ring_positions=_blocked_ring_positions(bot, ct)
            | _visible_friendly_ring_sentinels(bot, ct, enemy.position),
            legal_fire_fn=None,
            enemy_core_center=enemy_core_focus,
            current_anchor=live_anchor,
            site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
            connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
            committed_ring_position=committed_ring_position,
            committed_direction=committed_direction,
            allow_exploratory_fallback=False,
            profile=getattr(bot, "turn_profile", None),
        )
        if site is None:
            abandoned.append((enemy.position, NO_ACTIONABLE_SITE_REASON))
            continue
        score = (
            0 if live_anchor == enemy.position else 1,
            0 if not site.threatened else 1,
            0 if site.target.entity_type in assault.TURRET_TYPES else 1,
            0 if site.hits_core_center else 1,
            site.turns_to_useful_shot,
            -site.uncovered_logistics_gain,
            -site.marginal_value,
            -site.uncovered_target_count,
            (
                assault.manhattan(site.harvester_position, enemy_core_focus)
                if enemy_core_focus is not None
                else 9999
            ),
            assault.manhattan(ct.get_position(), site.ring_position),
            -site.cluster_size,
            -site.usable_sides,
            -site.immediate_open_sides,
            enemy.position.x + (enemy.position.y * ct.get_map_width()),
        )
        if best is None or score < best[0]:
            best = (score, site)
    return (None if best is None else best[1], abandoned)


def _commit_site(bot, ct: Controller, site: assault.AssaultSite) -> None:
    previous_site = getattr(bot, "assault_committed_site", None)
    bot.assault_committed_site = site
    bot.assault_committed_site_round = ct.get_current_round()
    if previous_site != site:
        _clear_execute_state(bot)
        _reset_nav_progress(bot)
    utils.bump_profile(bot, "assault_site_commits")


def _committed_site_is_valid(
    bot,
    ct: Controller,
    site: assault.AssaultSite,
    *,
    assessment: assault.AnchorAssessment | None,
) -> bool:
    current_round = ct.get_current_round()
    anchor_visible_now = any(
        enemy.entity_type == EntityType.HARVESTER
        and enemy.position == site.harvester_position
        for enemy in _assault_enemies(bot)
    )
    if (
        not anchor_visible_now
        and current_round - getattr(bot, "assault_committed_site_round", -9999)
        > ASSAULT_SITE_COMMIT_TTL
    ):
        return False
    if _is_anchor_blacklisted(bot, site.harvester_position, current_round):
        return False
    if _is_locally_claimed_assault_anchor(bot, site.harvester_position):
        return False
    if _is_in_exhausted_region(bot, site.harvester_position, current_round):
        return False
    if assessment is not None and assessment.status != assault.ANCHOR_LIVE:
        return False
    classification = assault.classify_ring_site(
        grid=bot.grid,
        ring_position=site.ring_position,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
    )
    if classification not in {assault.RING_IMMEDIATE, assault.RING_CLEARABLE}:
        return False
    return True


def _reusable_committed_site(
    bot,
    ct: Controller,
    *,
    live_anchor: Position | None,
    live_assessment: assault.AnchorAssessment | None,
    cache: dict[tuple[int, int], assault.AnchorAssessment] | None = None,
) -> tuple[assault.AssaultSite | None, assault.AnchorAssessment | None]:
    site = getattr(bot, "assault_committed_site", None)
    if site is None:
        return None, live_assessment

    assessment = live_assessment
    if live_anchor != site.harvester_position:
        assessment = _anchor_assessment(
            bot,
            ct,
            site.harvester_position,
            enemies=_assault_enemies(bot),
            cache=cache,
        )

    if not _committed_site_is_valid(bot, ct, site, assessment=assessment):
        utils.bump_profile(bot, "assault_site_invalidations")
        _clear_committed_site(bot)
        return None, live_assessment

    utils.bump_profile(bot, "assault_site_reuses")
    return site, assessment


def _move_toward(
    bot,
    ct: Controller,
    target: Position,
    *,
    build_road: bool = True,
    allow_enemy_builder_at_target: bool = False,
) -> None:
    bot.logger.log(f"assault moving toward {target}")
    navigation.assault_move_towards(
        bot,
        ct,
        target,
        build_road=build_road,
        allow_enemy_builder_at_target=allow_enemy_builder_at_target,
    )


def _execute_bootstrap_egress(bot, ct: Controller) -> bool:
    _refresh_bootstrap_egress_state(bot, ct)
    if not bootstrap_egress_active(bot, ct):
        return False

    bot.assault_subrole = "bootstrap"
    utils.set_profile(bot, "assault_subrole", "bootstrap")
    _bootstrap_egress_step(bot, ct)
    _refresh_bootstrap_egress_state(bot, ct)
    return True


def _execute_opening_escape(bot, ct: Controller) -> bool:
    return _execute_bootstrap_egress(bot, ct)


def execute_bootstrap_egress_only(bot, ct: Controller) -> bool:
    return _execute_bootstrap_egress(bot, ct)


def execute_opening_escape_only(bot, ct: Controller) -> bool:
    return _execute_bootstrap_egress(bot, ct)


def _tile_has_friendly_sentinel_now(bot, ct: Controller, position: Position) -> bool:
    utils.bump_profile(bot, "assault_get_tile_building_id_calls")
    building_id = ct.get_tile_building_id(position)
    if building_id is None:
        return False
    return (
        ct.get_entity_type(building_id) == EntityType.SENTINEL
        and ct.get_team(building_id) == ct.get_team()
    )


def _tile_has_other_builder_now(bot, ct: Controller, position: Position) -> bool:
    get_tile_builder_bot_id = getattr(ct, "get_tile_builder_bot_id", None)
    if get_tile_builder_bot_id is None:
        return False
    utils.bump_profile(bot, "assault_get_tile_builder_bot_id_calls")
    builder_id = get_tile_builder_bot_id(position)
    return builder_id is not None and builder_id != ct.get_id()


def _destroy_buildable_ring_building_if_present(
    bot,
    ct: Controller,
    position: Position,
) -> bool:
    utils.bump_profile(bot, "assault_get_tile_building_id_calls")
    building_id = ct.get_tile_building_id(position)
    if building_id is None:
        return False
    building_type = ct.get_entity_type(building_id)
    building_team = ct.get_team(building_id)
    if building_type in {EntityType.ROAD, EntityType.MARKER} and building_team == ct.get_team():
        pass
    else:
        return False
    if not ct.can_destroy(position):
        return False
    ct.destroy(position)
    return True


def _best_confirmed_scout_anchor(
    bot,
    ct: Controller,
    current_round: int,
) -> Position | None:
    best: tuple[tuple[int, int, int, int], Position] | None = None
    for position_key, seen_round in getattr(bot, "confirmed_enemy_harvesters", {}).items():
        position = Position(position_key[0], position_key[1])
        if _is_anchor_blacklisted(bot, position, current_round):
            continue
        if _is_locally_claimed_assault_anchor(bot, position):
            continue
        if _is_in_exhausted_region(bot, position, current_round):
            continue
        score = (
            current_round - seen_round,
            assault.manhattan(ct.get_position(), position),
            position.x,
            position.y,
        )
        if best is None or score < best[0]:
            best = (score, position)
    return None if best is None else best[1]


def _best_predicted_scout_anchor(
    bot,
    ct: Controller,
    current_round: int,
) -> Position | None:
    predicted_enemy_harvesters = [
        candidate
        for candidate in getattr(bot, "predicted_enemy_harvesters", [])
        if not _is_anchor_blacklisted(bot, candidate.position, current_round)
        and not _is_locally_claimed_assault_anchor(bot, candidate.position)
        and not _is_in_exhausted_region(bot, candidate.position, current_round)
    ]
    if not predicted_enemy_harvesters:
        return None

    predicted_enemy_harvesters.sort(
        key=lambda candidate: (
            candidate.source_rank,
            0 if candidate.mode == bot.best_symmetry_mode else 1,
            0 if not candidate.same_lane else 1,
            candidate.travel_distance,
            candidate.position.x,
            candidate.position.y,
        )
    )
    return assault.choose_predicted_scout_anchor(
        predicted_enemy_harvesters=predicted_enemy_harvesters,
        spawn_slot=bot.spawn_slot,
        current_round=current_round,
    )


def _choose_scout_target(
    bot,
    ct: Controller,
    *,
    live_anchor: Position | None,
) -> Position | None:
    current_round = ct.get_current_round()
    saw_new_ore = _note_new_ore(bot)
    bot.discovery_turns_without_new_ore += 1
    if saw_new_ore:
        bot.discovery_turns_without_new_ore = 0

    force_frontier = bot.discovery_turns_without_new_ore > DISCOVERY_STALE_THRESHOLD
    if force_frontier:
        _clear_scout_state(bot)
    else:
        cached_target = _cached_scout_target(bot, ct)
        if cached_target is not None:
            bot.logger.log(f"reusing scout target {cached_target}")
            return cached_target

    confirmed_anchor = _best_confirmed_scout_anchor(bot, ct, current_round)
    if confirmed_anchor is not None:
        target = _normalize_scout_target(bot, ct, confirmed_anchor)
        if target is not None:
            _remember_scout_target(bot, ct, target, anchor=confirmed_anchor)
            return target

    if not force_frontier:
        predicted_anchor = _best_predicted_scout_anchor(bot, ct, current_round)
        if predicted_anchor is not None:
            target = _normalize_scout_target(bot, ct, predicted_anchor)
            if target is not None:
                _remember_scout_target(bot, ct, target, anchor=predicted_anchor)
                return target

    frontier_target = _select_enemy_half_frontier_target(
        bot,
        ct,
        anchor_hint=bot.enemy_core_anchor or live_anchor,
    )
    if frontier_target is None:
        return None

    bot.discovery_turns_without_new_ore = 0
    _remember_scout_target(bot, ct, frontier_target, anchor=None)
    bot.recent_assault_waypoints[(frontier_target.x, frontier_target.y)] = current_round
    return frontier_target


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


def _select_enemy_half_frontier_target(
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
    candidates: list[tuple[tuple[int, int, int, int, int, int, int], Position]] = []

    for chunk_x in range(chunk_cols):
        for chunk_y in range(chunk_rows):
            chunk = (chunk_x, chunk_y)
            raw_target = _chunk_center(
                chunk,
                map_width=map_width,
                map_height=map_height,
            )
            enemy_side, forward = _enemy_half_metrics(
                bot,
                raw_target,
                anchor_hint=anchor_hint or bot.enemy_core_anchor,
            )
            if not enemy_side:
                continue
            target = _normalize_scout_target(bot, ct, raw_target)
            if target is None:
                continue
            if _is_in_exhausted_region(bot, target, current_round):
                continue
            unseen, stale = _chunk_last_seen(bot, chunk, current_round=current_round)
            candidates.append(
                (
                    (
                        0 if unseen > 0 else 1,
                        -stale,
                        0 if (target.x, target.y) not in recent_waypoints else 1,
                        -forward,
                        max(
                            abs(chunk[0] - current_chunk[0]),
                            abs(chunk[1] - current_chunk[1]),
                        ),
                        assault.manhattan(current_pos, target),
                        target.x + (target.y * map_width),
                    ),
                    target,
                )
            )

    if not candidates:
        return _select_global_enemy_frontier_target(
            bot,
            ct,
            anchor_hint=anchor_hint,
            enemy_half_only=True,
        )

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _is_interesting_frontier_chunk(unseen: int, stale: int) -> bool:
    return unseen > 0 or stale >= ASSAULT_GLOBAL_FRONTIER_STALE_MIN


def _select_global_enemy_frontier_target(
    bot,
    ct: Controller,
    *,
    anchor_hint: Position | None,
    enemy_half_only: bool = False,
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
            if enemy_half_only and not enemy_side:
                continue
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


def _ring_distance(current_pos: Position, ring_pos: Position) -> int:
    return max(abs(current_pos.x - ring_pos.x), abs(current_pos.y - ring_pos.y))


def _execute_state_matches_site(bot, site: assault.AssaultSite) -> bool:
    state = getattr(bot, "assault_execute_state", {})
    return (
        state.get("anchor") == (site.harvester_position.x, site.harvester_position.y)
        and state.get("ring") == (site.ring_position.x, site.ring_position.y)
        and state.get("direction") == site.sentinel_direction.name
    )


def _set_execute_subplan(bot, site: assault.AssaultSite, subplan: str) -> None:
    bot.assault_execute_state = {
        "subplan": subplan,
        "anchor": (site.harvester_position.x, site.harvester_position.y),
        "ring": (site.ring_position.x, site.ring_position.y),
        "direction": site.sentinel_direction.name,
        "wait_turns": 0,
        "fire_wait_turns": 0,
    }


def _classify_execute_subplan(
    bot,
    ct: Controller,
    site: assault.AssaultSite,
) -> str:
    ring_position = site.ring_position
    if _tile_has_friendly_sentinel_now(bot, ct, ring_position):
        return "DONE"
    if _tile_has_other_builder_now(bot, ct, ring_position):
        return "WAIT_FOR_SLOT"

    classification = assault.classify_ring_site(
        grid=bot.grid,
        ring_position=ring_position,
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
    )
    if classification == assault.RING_IMMEDIATE:
        return "BUILD"
    if classification == assault.RING_CLEARABLE:
        return "CLEAR_THEN_BUILD"
    return "BLOCKED"


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


def _should_hold_build_window(ct: Controller) -> bool:
    get_action_cooldown = getattr(ct, "get_action_cooldown", None)
    if callable(get_action_cooldown):
        try:
            if get_action_cooldown() > 0:
                return True
        except Exception:
            pass
    return _can_afford_sentinel(ct)


def _update_approach_progress(
    bot,
    target: Position,
    *,
    current_pos: Position,
    moved: bool,
    failure_reason: str | None,
) -> None:
    target_key = (target.x, target.y)
    if getattr(bot, "assault_nav_progress_target", None) != target_key:
        _reset_nav_progress(bot)
        bot.assault_nav_progress_target = target_key

    if failure_reason is not None:
        bot.assault_nav_failure_count += 1
    elif moved:
        bot.assault_nav_failure_count = 0

    current_dist = _ring_distance(current_pos, target)
    if current_dist < bot.assault_best_dist_to_ring:
        bot.assault_best_dist_to_ring = current_dist
        bot.assault_progress_stall_count = 0
    else:
        bot.assault_progress_stall_count += 1


def _approach_site(bot, ct: Controller, site: assault.AssaultSite) -> None:
    bot.assault_subrole = "approach"
    utils.set_profile(bot, "assault_subrole", "approach")
    current_pos = ct.get_position()

    if _is_harassable_enemy_building(bot, ct, current_pos) and ct.can_fire(current_pos):
        ct.fire(current_pos)
        bot.assault_last_progress_round = ct.get_current_round()
        return

    moved, failure_reason = navigation.assault_navigate(
        bot,
        ct,
        site.ring_position,
        build_road=True,
        allow_enemy_builder_at_target=True,
    )
    if moved:
        bot.assault_last_progress_round = ct.get_current_round()

    _update_approach_progress(
        bot,
        site.ring_position,
        current_pos=ct.get_position(),
        moved=moved,
        failure_reason=failure_reason,
    )
    if (
        bot.assault_nav_failure_count >= NAV_FAILURE_LIMIT
        or bot.assault_progress_stall_count >= PROGRESS_STALL_LIMIT
    ):
        _retire_anchor(bot, ct, site.harvester_position, reason="navigation_blocked")


def _execute_build_subplan(bot, ct: Controller, site: assault.AssaultSite) -> bool:
    refreshed_subplan = _classify_execute_subplan(bot, ct, site)
    if refreshed_subplan == "DONE":
        _retire_anchor(bot, ct, site.harvester_position, reason="captured")
        return True
    if refreshed_subplan == "BLOCKED":
        _retire_anchor(bot, ct, site.harvester_position, reason="ring_blocked")
        return True
    if refreshed_subplan != "BUILD":
        _set_execute_subplan(bot, site, refreshed_subplan)
        return _execute_committed_site(bot, ct, site)

    state = getattr(bot, "assault_execute_state", {})
    ring_position = site.ring_position
    current_pos = ct.get_position()
    ring_distance = _ring_distance(current_pos, ring_position)

    if ring_distance > 1:
        staging = _best_sidestep(bot, ct, ring_position, site.harvester_position) or ring_position
        moved, failure_reason = navigation.assault_navigate(
            bot,
            ct,
            staging,
            build_road=True,
            allow_enemy_builder_at_target=True,
        )
        if moved:
            bot.assault_last_progress_round = ct.get_current_round()
        _update_approach_progress(
            bot,
            staging,
            current_pos=ct.get_position(),
            moved=moved,
            failure_reason=failure_reason,
        )
        if (
            bot.assault_nav_failure_count >= NAV_FAILURE_LIMIT
            or bot.assault_progress_stall_count >= PROGRESS_STALL_LIMIT
        ):
            _retire_anchor(bot, ct, site.harvester_position, reason="navigation_blocked")
        return True

    if ring_distance == 0:
        sidestep = _best_sidestep(bot, ct, ring_position, site.harvester_position)
        if sidestep is not None:
            move_dir = current_pos.direction_to(sidestep)
            if move_dir is not None and ct.can_move(move_dir):
                ct.move(move_dir)
                bot.assault_last_progress_round = ct.get_current_round()
                return True
        _set_execute_subplan(bot, site, "WAIT_FOR_SLOT")
        return True

    _destroy_buildable_ring_building_if_present(bot, ct, ring_position)
    utils.bump_profile(bot, "assault_can_build_sentinel_calls")
    if ct.can_build_sentinel(ring_position, site.sentinel_direction):
        utils.bump_profile(bot, "assault_can_build_sentinel_true")
        ct.build_sentinel(ring_position, site.sentinel_direction)
        bot.assault_last_progress_round = ct.get_current_round()
        _retire_anchor(bot, ct, site.harvester_position, reason="captured")
        return True
    if _tile_has_friendly_sentinel_now(bot, ct, ring_position):
        _retire_anchor(bot, ct, site.harvester_position, reason="captured")
        return True
    if _tile_has_other_builder_now(bot, ct, ring_position):
        _set_execute_subplan(bot, site, "WAIT_FOR_SLOT")
        return True
    if _should_hold_build_window(ct):
        state["wait_turns"] = state.get("wait_turns", 0) + 1
        if state["wait_turns"] >= BUILD_WINDOW_WAIT_TTL:
            _retire_anchor(bot, ct, site.harvester_position, reason="wait_timeout")
        return True
    _retire_anchor(bot, ct, site.harvester_position, reason="wait_timeout")
    return True


def _execute_clear_then_build_subplan(bot, ct: Controller, site: assault.AssaultSite) -> bool:
    refreshed_subplan = _classify_execute_subplan(bot, ct, site)
    if refreshed_subplan == "DONE":
        _retire_anchor(bot, ct, site.harvester_position, reason="captured")
        return True
    if refreshed_subplan == "BLOCKED":
        _retire_anchor(bot, ct, site.harvester_position, reason="ring_blocked")
        return True
    if refreshed_subplan != "CLEAR_THEN_BUILD":
        _set_execute_subplan(bot, site, refreshed_subplan)
        return _execute_committed_site(bot, ct, site)

    state = getattr(bot, "assault_execute_state", {})
    ring_position = site.ring_position
    current_pos = ct.get_position()
    ring_distance = _ring_distance(current_pos, ring_position)

    if ring_distance > 1:
        staging = _best_sidestep(bot, ct, ring_position, site.harvester_position) or ring_position
        moved, failure_reason = navigation.assault_navigate(
            bot,
            ct,
            staging,
            build_road=True,
            allow_enemy_builder_at_target=True,
        )
        if moved:
            bot.assault_last_progress_round = ct.get_current_round()
        _update_approach_progress(
            bot,
            staging,
            current_pos=ct.get_position(),
            moved=moved,
            failure_reason=failure_reason,
        )
        if (
            bot.assault_nav_failure_count >= NAV_FAILURE_LIMIT
            or bot.assault_progress_stall_count >= PROGRESS_STALL_LIMIT
        ):
            _retire_anchor(bot, ct, site.harvester_position, reason="navigation_blocked")
        return True

    if ring_distance == 1:
        if _tile_has_other_builder_now(bot, ct, ring_position):
            _set_execute_subplan(bot, site, "WAIT_FOR_SLOT")
            return True
        if not _is_clearable_enemy_ring_building(bot, ct, ring_position):
            _set_execute_subplan(bot, site, "BUILD")
            return _execute_build_subplan(bot, ct, site)
        move_dir = current_pos.direction_to(ring_position)
        if move_dir is not None and ct.can_move(move_dir):
            ct.move(move_dir)
            bot.assault_last_progress_round = ct.get_current_round()
            return True
        bot.assault_nav_failure_count += 1
        if bot.assault_nav_failure_count >= NAV_FAILURE_LIMIT:
            _retire_anchor(bot, ct, site.harvester_position, reason="navigation_blocked")
        return True

    if _is_clearable_enemy_ring_building(bot, ct, ring_position):
        if ct.can_fire(current_pos):
            ct.fire(current_pos)
            bot.assault_last_progress_round = ct.get_current_round()
            state["fire_wait_turns"] = 0
            return True
        state["fire_wait_turns"] = state.get("fire_wait_turns", 0) + 1
        if state["fire_wait_turns"] >= FIRE_WAIT_TTL:
            _retire_anchor(bot, ct, site.harvester_position, reason="ring_blocked")
        return True

    sidestep = _best_sidestep(bot, ct, ring_position, site.harvester_position)
    if sidestep is not None:
        move_dir = current_pos.direction_to(sidestep)
        if move_dir is not None and ct.can_move(move_dir):
            ct.move(move_dir)
            bot.assault_last_progress_round = ct.get_current_round()
            _set_execute_subplan(bot, site, "BUILD")
            return True
    return True


def _execute_wait_for_slot_subplan(bot, ct: Controller, site: assault.AssaultSite) -> bool:
    state = getattr(bot, "assault_execute_state", {})
    if _is_locally_claimed_assault_anchor(bot, site.harvester_position):
        _retire_anchor(bot, ct, site.harvester_position, reason="coordination_yield")
        return True

    ring_position = site.ring_position
    if _tile_has_other_builder_now(bot, ct, ring_position):
        state["wait_turns"] = state.get("wait_turns", 0) + 1
        if state["wait_turns"] >= WAIT_FOR_SLOT_TTL:
            _retire_anchor(bot, ct, site.harvester_position, reason="wait_timeout")
        return True

    subplan = _classify_execute_subplan(bot, ct, site)
    if subplan == "DONE":
        _retire_anchor(bot, ct, site.harvester_position, reason="captured")
        return True
    if subplan == "BLOCKED":
        _retire_anchor(bot, ct, site.harvester_position, reason="ring_blocked")
        return True

    _set_execute_subplan(bot, site, subplan)
    return _execute_committed_site(bot, ct, site)


def _execute_committed_site(bot, ct: Controller, site: assault.AssaultSite) -> bool:
    bot.assault_subrole = "execute"
    utils.set_profile(bot, "assault_subrole", "execute")

    if not _execute_state_matches_site(bot, site):
        subplan = _classify_execute_subplan(bot, ct, site)
        if subplan == "DONE":
            _retire_anchor(bot, ct, site.harvester_position, reason="captured")
            return True
        if subplan == "BLOCKED":
            _retire_anchor(bot, ct, site.harvester_position, reason="ring_blocked")
            return True
        _set_execute_subplan(bot, site, subplan)

    subplan = bot.assault_execute_state.get("subplan")
    if subplan == "BUILD":
        return _execute_build_subplan(bot, ct, site)
    if subplan == "CLEAR_THEN_BUILD":
        return _execute_clear_then_build_subplan(bot, ct, site)
    if subplan == "WAIT_FOR_SLOT":
        return _execute_wait_for_slot_subplan(bot, ct, site)
    return False


def execute(bot, ct: Controller):
    _refresh_opening_escape_state(bot, ct)
    if _execute_opening_escape(bot, ct):
        return

    enemies = _assault_enemies(bot)
    _aa_cache: dict[tuple[int, int], assault.AnchorAssessment] = {}
    utils.set_profile(bot, "assault_visible_enemies", len(enemies))
    utils.set_profile(
        bot,
        "assault_visible_harvesters",
        sum(1 for enemy in enemies if enemy.entity_type == EntityType.HARVESTER),
    )
    _refresh_anchor_blacklist(bot, ct.get_current_round())
    _refresh_exhausted_regions(bot, ct.get_current_round())
    _refresh_exhausted_sectors(bot, ct.get_current_round())
    _update_enemy_inference(bot, ct)
    visible_harvesters = {
        enemy.position
        for enemy in enemies
        if enemy.entity_type == EntityType.HARVESTER
    }

    live_anchor = _live_anchor(bot, ct, enemies)
    if live_anchor is not None and _is_locally_claimed_assault_anchor(bot, live_anchor):
        _retire_anchor(bot, ct, live_anchor, reason="coordination_yield")
        live_anchor = None

    live_assessment = None
    if live_anchor is not None:
        live_assessment = _anchor_assessment(bot, ct, live_anchor, enemies=enemies, cache=_aa_cache)
        bot.assault_anchor_status = live_assessment.status
        if live_assessment.status != assault.ANCHOR_LIVE:
            _retire_anchor(bot, ct, live_anchor, reason=live_assessment.status)
            live_anchor = None
    else:
        bot.assault_anchor_status = None

    chosen_site = None
    chosen_assessment = live_assessment
    chosen_site, chosen_assessment = _reusable_committed_site(
        bot,
        ct,
        live_anchor=live_anchor,
        live_assessment=live_assessment,
        cache=_aa_cache,
    )
    live_anchor_visible = live_anchor in visible_harvesters if live_anchor is not None else False
    if chosen_site is None and live_anchor is not None and not live_anchor_visible:
        chosen_site = _best_site_for_anchor(bot, ct, live_anchor)
        if chosen_site is not None:
            chosen_assessment = live_assessment
    if chosen_site is None:
        chosen_site, abandoned_visible_anchors = _best_visible_site(
            bot,
            ct,
            live_anchor,
            cache=_aa_cache,
        )
        abandoned_keys = {
            (position.x, position.y)
            for position, _reason in abandoned_visible_anchors
        }
        for position, reason in abandoned_visible_anchors:
            _abandon_anchor_candidate(bot, ct, position, reason=reason)
        if live_anchor is not None and (live_anchor.x, live_anchor.y) in abandoned_keys:
            live_anchor = None
            live_assessment = None
            if getattr(bot, "harvester_anchor", None) is None:
                bot.assault_anchor_status = None
        if chosen_site is not None and (
            chosen_assessment is None
            or chosen_site.harvester_position != live_anchor
        ):
            chosen_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
                cache=_aa_cache,
            )

    if chosen_site is not None:
        if getattr(bot, "assault_committed_site", None) != chosen_site:
            _commit_site(bot, ct, chosen_site)

        ring_key = (chosen_site.ring_position.x, chosen_site.ring_position.y)
        utils.set_profile(bot, "assault_selected_anchor", (chosen_site.harvester_position.x, chosen_site.harvester_position.y))
        utils.set_profile(bot, "assault_selected_ring", ring_key)
        _publish_assault_claim(bot, ct, chosen_site.harvester_position)
        _clear_scout_state(bot)
        bot.harvester_anchor = chosen_site.harvester_position
        bot.harvester_anchor_last_seen_round = ct.get_current_round()
        bot.assault_last_site_signature = _site_signature(chosen_site)
        if _ring_distance(ct.get_position(), chosen_site.ring_position) <= 1:
            _execute_committed_site(bot, ct, chosen_site)
        else:
            _approach_site(bot, ct, chosen_site)
        return

    scout_target = _choose_scout_target(bot, ct, live_anchor=live_anchor)
    if scout_target is not None:
        bot.assault_subrole = "scout"
        utils.set_profile(bot, "assault_subrole", "scout")
        moved, _failure_reason = navigation.assault_navigate(
            bot,
            ct,
            scout_target,
            build_road=True,
            allow_enemy_builder_at_target=True,
        )
        if moved:
            bot.assault_last_progress_round = ct.get_current_round()
