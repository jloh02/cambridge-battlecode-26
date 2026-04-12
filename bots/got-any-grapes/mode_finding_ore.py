from cambc import Controller, Position, EntityType
from states import BuilderMode, TargetKind
import utils
import navigation
import mode_exploring
import marker
from collections import deque

MINIMUM_RESOURCE_TO_MINE_AXIONITE = 800
MINIMUM_AXIONITE_ROUND = 100
ORE_TARGET_STUCK_RETRY_TURNS = 6
ORE_TARGET_BLACKLIST_TTL = 15
EARLY_ORE_TARGET_STUCK_RETRY_TURNS = 3
EARLY_ORE_TARGET_STUCK_MAX_ROUND = 60
EARLY_ORE_TARGET_STUCK_MAX_MANHATTAN = 3

# Cached set used by adjacent-conveyor checks; defining at module load
# avoids re-allocating the set on every call.
_MFO_TRANSPORT_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
})


def _tuple_to_pos(pos_tuple: tuple[int, int]) -> Position:
    return Position(pos_tuple[0], pos_tuple[1])


def _has_adjacent_conveyor(bot, ct: Controller, ore_pos: Position) -> bool:
    """Check if ore already has an adjacent friendly conveyor."""
    my_team = ct.get_team()
    grid_get = bot.grid.get
    for d in utils.CARDINAL_DIRECTIONS:
        neighbor = ore_pos.add(d)
        neighbor_data = grid_get((neighbor.x, neighbor.y))
        if neighbor_data is None:
            continue
        if neighbor_data.get("building") in _MFO_TRANSPORT_TYPES:
            if neighbor_data.get("building_team") == my_team:
                return True
    return False


def _transport_has_visible_backpressure(bot, ct: Controller, pos: Position) -> bool:
    tile_data = bot.grid.get((pos.x, pos.y))
    if tile_data is None:
        return False
    building_id = tile_data.get("building_id")
    if building_id is None:
        return False

    get_stored_resource_id = getattr(ct, "get_stored_resource_id", None)
    if get_stored_resource_id is not None:
        stored_id = get_stored_resource_id(building_id)
        if stored_id is not None:
            return True

    get_stored_resource = getattr(ct, "get_stored_resource", None)
    if get_stored_resource is None:
        return False
    stored_resource = get_stored_resource(building_id)
    return stored_resource is not None


def _adjacent_friendly_conveyor_info(bot, ct: Controller, ore_pos: Position) -> tuple[int, bool]:
    my_team = ct.get_team()
    adjacent_count = 0
    has_backpressure = False
    grid_get = bot.grid.get
    for d in utils.CARDINAL_DIRECTIONS:
        neighbor = ore_pos.add(d)
        neighbor_data = grid_get((neighbor.x, neighbor.y))
        if neighbor_data is None:
            continue
        building = neighbor_data.get("building")
        if building in _MFO_TRANSPORT_TYPES and neighbor_data.get("building_team") == my_team:
            adjacent_count += 1
            if _transport_has_visible_backpressure(bot, ct, neighbor):
                has_backpressure = True

    return adjacent_count, has_backpressure


def _can_start_secondary_return_route(bot, ct: Controller) -> bool:
    current_pos = ct.get_position()
    current_data = bot.grid.get((current_pos.x, current_pos.y))
    building = current_data.get("building") if current_data is not None else None
    if building is None or building is EntityType.ROAD or building is EntityType.MARKER:
        return True

    # If the builder is already standing on friendly transport, rebuilding from
    # that tile risks tearing up the working lane we are trying to supplement.
    return False


def _cached_access_point(bot, ct: Controller, ore_pos, from_pos, cache: dict):
    key = (ore_pos.x, ore_pos.y, from_pos.x, from_pos.y)
    if key not in cache:
        cache[key] = utils.closest_non_obstacle_cardinal_point_on_grid(
            bot, ct, ore_pos, from_pos
        )
    return cache[key]


def _refresh_ore_target_blacklist(bot, current_round: int) -> None:
    bot.ore_target_blacklist = {
        key: expiry_round
        for key, expiry_round in getattr(bot, "ore_target_blacklist", {}).items()
        if expiry_round > current_round
    }


def _is_ore_temporarily_blocked(bot, ore_pos: Position, current_round: int) -> bool:
    return getattr(bot, "ore_target_blacklist", {}).get((ore_pos.x, ore_pos.y), -1) > current_round


def _reset_ore_target_state(bot) -> None:
    bot.ore_target_state = {
        "ore": None,
        "access": None,
        "stuck_turns": 0,
    }


def _note_ore_target_progress(
    bot,
    ct: Controller,
    ore_pos: Position,
    access_pos: Position,
    *,
    moved: bool,
) -> bool:
    current_round = ct.get_current_round()
    ore_key = (ore_pos.x, ore_pos.y)
    access_key = (access_pos.x, access_pos.y)
    state = getattr(bot, "ore_target_state", {})
    if state.get("ore") != ore_key or state.get("access") != access_key:
        state = {
            "ore": ore_key,
            "access": access_key,
            "stuck_turns": 0,
        }

    if moved:
        state["stuck_turns"] = 0
        bot.ore_target_state = state
        return False

    state["stuck_turns"] = state.get("stuck_turns", 0) + 1
    bot.ore_target_state = state
    retry_turns = ORE_TARGET_STUCK_RETRY_TURNS
    if (
        getattr(bot, "spawn_pos", None) is not None
        and getattr(bot, "last_harvester_pos", None) is None
        and current_round <= EARLY_ORE_TARGET_STUCK_MAX_ROUND
    ):
        current_pos = ct.get_position()
        if utils.manhattan(current_pos, bot.spawn_pos) <= EARLY_ORE_TARGET_STUCK_MAX_MANHATTAN:
            retry_turns = EARLY_ORE_TARGET_STUCK_RETRY_TURNS

    if state["stuck_turns"] < retry_turns:
        return False

    bot.ore_target_blacklist[ore_key] = current_round + ORE_TARGET_BLACKLIST_TTL
    bot.logger.log(f"temporarily blacklisting ore target {ore_pos} after route stalls")
    _reset_ore_target_state(bot)
    return True


def _find_best_ore_target(bot, ct: Controller, max_bfs_nodes=None):
    """
    Finds the closest ore using a BFS flood-fill to account for walls and pathing.
    Falls back to Euclidean distance if the nearest ore is extremely far away.

    Skips ore that already has adjacent friendly conveyors and skips claimed harvesters.
    """
    if not bot.titanium_locations:
        return None

    start_pos = ct.get_position()
    visited = {(start_pos.x, start_pos.y)}
    queue = deque([(start_pos, 0)])

    known_obstacles = bot.pathfinding_state["known_obstacles"]
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()

    # Scale BFS budget with map size so sparse maps get a fairer search.
    if max_bfs_nodes is None:
        map_area = map_w * map_h
        if map_area <= 600:      # small maps (≤~24x25)
            max_bfs_nodes = 50
        elif map_area <= 1200:   # medium maps (≤~35x35)
            max_bfs_nodes = 80
        else:                    # large maps
            max_bfs_nodes = 120

    nodes_expanded = 0
    current_round = ct.get_current_round()

    # 1. Bounded BFS for the true pathing-closest ore
    while queue and nodes_expanded < max_bfs_nodes:
        current, dist = queue.popleft()
        nodes_expanded += 1

        # Check cardinal neighbors
        for d in utils.CARDINAL_DIRECTIONS:
            neighbor = current.add(d)
            nx, ny = neighbor.x, neighbor.y
            n_tuple = (nx, ny)

            # Bounds check
            if not (0 <= nx < map_w and 0 <= ny < map_h):
                continue

            # Did we find an ore?
            if neighbor in bot.titanium_locations:
                if _is_ore_temporarily_blocked(bot, neighbor, current_round):
                    continue
                # Skip if already has adjacent conveyor
                if _has_adjacent_conveyor(bot, ct, neighbor):
                    continue

                # Skip if it's a claimed harvester (one we've already connected)
                if n_tuple in bot.claimed_harvesters:
                    continue

                # Deconfliction: Check if another friendly bot is practically standing on it
                if _is_ore_claimed_by_friend(bot, ct, neighbor):
                    continue
                return (neighbor, current, dist + 1)

            # Standard expansion
            if n_tuple not in visited and n_tuple not in known_obstacles:
                # Optional: You can add a quick check against your bot.grid here
                # to ensure the tile doesn't have an impassable building.
                visited.add(n_tuple)
                queue.append((neighbor, dist + 1))

    # 2. Fallback: If BFS maxes out (meaning the nearest ore is very far),
    # fall back to your existing Euclidean heuristic logic.
    return _find_best_ore_target_euclidean(bot, ct)


def _find_best_ore_target_euclidean(bot, ct: Controller):
    """Original logic: Finds the closest ore using straight-line distance.

    Skips ore that already have adjacent friendly conveyors and skips claimed harvesters.
    """
    if not (bot.titanium_locations or bot.axionite_locations):
        return None

    access_cache = {}
    my_pos = ct.get_position()
    best_candidate = None
    best_key = None
    current_round = ct.get_current_round()
    for pos in utils.get_eligible_ore_locations(bot, ct):
        if _is_ore_temporarily_blocked(bot, pos, current_round):
            continue
        # Skip if already has adjacent conveyor
        if _has_adjacent_conveyor(bot, ct, pos):
            continue

        # Skip if it's a claimed harvester
        if (pos.x, pos.y) in bot.claimed_harvesters:
            continue

        closest_pos = _cached_access_point(bot, ct, pos, my_pos, access_cache)
        if closest_pos is None:
            continue  # No valid adjacent position to target this ore
        d = my_pos.distance_squared(closest_pos)

        # Ensure no other friendly bot is closer
        claimed_by_friend = False
        for bot_pos in bot.bot_locations:
            friend_pos = _tuple_to_pos(bot_pos)
            friend_access = _cached_access_point(bot, ct, pos, friend_pos, access_cache)
            if friend_access is None:
                continue
            if d > friend_pos.distance_squared(friend_access):
                claimed_by_friend = True
                break

        if claimed_by_friend:
            continue

        # Same strategy as `jon-5`, cheaper execution: avoid sorting the full
        # candidate list when the final choice is still "minimum distance with a
        # deterministic tie-break".
        candidate_key = (d, closest_pos.x, closest_pos.y, pos.x, pos.y)
        if best_key is None or candidate_key < best_key:
            best_key = candidate_key
            best_candidate = (pos, closest_pos, d)

    return best_candidate  # Returns (pos, closest_pos, distance)


def _is_ore_claimed_by_friend(bot, ct: Controller, ore_pos: Position) -> bool:
    """Returns True if another friendly bot is closer (or wins tie-break) to ore access."""
    my_pos = ct.get_position()
    access_cache = {}
    my_access = _cached_access_point(bot, ct, ore_pos, my_pos, access_cache)
    if my_access is None:
        return True

    my_dist = my_pos.distance_squared(my_access)
    my_tuple = (my_pos.x, my_pos.y)

    for bot_pos_tuple in bot.bot_locations:
        # Ignore ourselves if our own position appears in the sensed ally set.
        if bot_pos_tuple == my_tuple:
            continue

        friend_pos = _tuple_to_pos(bot_pos_tuple)
        friend_access = _cached_access_point(bot, ct, ore_pos, friend_pos, access_cache)
        if friend_access is None:
            continue

        friend_dist = friend_pos.distance_squared(friend_access)
        if friend_dist < my_dist or (
            friend_dist == my_dist and bot_pos_tuple < my_tuple
        ):
            return True
    return False


def _determine_return_target(bot, start_pos):
    """Calculates whether returning to the core or a nearby conveyor is more efficient."""
    visible_candidates = list(bot.connected_friendly_conveyors.items())
    best_target = utils.closest_point_on_grid(bot.core_pos, start_pos)
    best_dist = utils.manhattan(start_pos, best_target)
    best_score = best_dist
    best_kind = TargetKind.CORE

    if visible_candidates and not getattr(bot, "tiling_prefer_core_return", False):
        nearest_c_tuple, _ = min(
            visible_candidates,
            key=lambda item: (
                abs(start_pos.x - item[0][0])
                + abs(start_pos.y - item[0][1])
                + navigation.connected_conveyor_load_penalty(item[1]),
                item[0][0],
                item[0][1],
            ),
        )
        nearest_c = Position(nearest_c_tuple[0], nearest_c_tuple[1])
        nearest_c_dist = utils.manhattan(start_pos, nearest_c)
        nearest_c_score = nearest_c_dist + navigation.connected_conveyor_load_penalty(
            bot.connected_friendly_conveyors.get(nearest_c_tuple, 0)
        )
        if nearest_c_score < best_score:
            best_target = nearest_c
            best_dist = nearest_c_dist
            best_score = nearest_c_score
            best_kind = TargetKind.CONVEYOR

    bot.return_target_pos = best_target
    bot.return_target_dist_manhatten = best_dist
    bot.return_target_kind = best_kind


def _enter_tiling_back_mode(
    bot,
    ore_pos: Position,
    *,
    force_core_return: bool = False,
):
    enter_tiling_back_from_origin(
        bot,
        ore_pos,
        origin_kind="HARVESTER",
        force_core_return=force_core_return,
    )


def enter_tiling_back_from_origin(
    bot,
    start_pos: Position,
    *,
    origin_kind: str,
    force_core_return: bool = False,
):
    bot.tiling_back_origin_kind = origin_kind
    if origin_kind == "HARVESTER":
        bot.last_harvester_pos = start_pos
    bot.tiled_back_positions = set()
    bot.nearest_conveyor_pos = None
    bot.nearest_conveyor_dist_manhatten = float("inf")
    bot.return_target_pos = None
    bot.return_target_dist_manhatten = float("inf")
    bot.core_return_target_pos = None
    bot.core_lane_slot_pos = None
    bot.core_lane_core_tile_pos = None
    bot.core_lane_exit_built = False
    bot.tiling_force_core_return = force_core_return
    prefer_direct_core = (
        origin_kind == "HARVESTER"
        and utils.should_prioritize_direct_core_return(
            bot.core_pos,
            start_pos,
        )
    )
    bot.tiling_prefer_core_return = force_core_return or prefer_direct_core
    bot.tiling_core_approach_full = False
    bot.last_return_target_refresh_round = -1

    bot.pathfinding_state["path"] = []
    bot.pathfinding_state["temporary_obstacles"] = {}
    bot.pathfinding_state["tiling_back_wait_turns"] = 0
    bot.pathfinding_state["last_replan_signature"] = None
    bot.pathfinding_state["last_replan_round"] = -1
    bot.pathfinding_state["planner_state"] = None
    bot.explore_target_chunk = None
    bot.explore_target_pos = None
    bot.pending_bridge_plan = None
    bot.pending_build = None
    bot.bridge_transit_path = None
    bot.bridge_transit_cooldown_until = -1

    bot.builder_mode = BuilderMode.TILING_BACK
    _determine_return_target(bot, start_pos)
    if bot.tiling_prefer_core_return:
        bot.return_target_pos = utils.closest_point_on_grid(bot.core_pos, start_pos)
        bot.return_target_dist_manhatten = utils.manhattan(
            start_pos,
            bot.return_target_pos,
        )
        bot.return_target_kind = TargetKind.CORE


def _build_harvester_and_switch_mode(bot, ct: Controller, ore_pos):
    """Handles construction and state transition when ore is reached.

    Checks if the harvester already has adjacent conveyors on the other end.
    If so, marks it as claimed and doesn't enter TILING_BACK mode.
    """
    bot.logger.log(f"building harvester {ore_pos}")
    ct.build_harvester(ore_pos)
    bot.last_harvester_place_round = ct.get_current_round()

    adjacent_friendly_conveyors, adjacent_has_backpressure = _adjacent_friendly_conveyor_info(
        bot,
        ct,
        ore_pos,
    )

    # If already connected, mark as claimed and continue finding ore
    if adjacent_friendly_conveyors > 0:
        if (
            adjacent_has_backpressure
            and _can_start_secondary_return_route(bot, ct)
        ):
            bot.logger.log(
                f"Harvester at {ore_pos} touches backpressured lane; "
                "building secondary core return"
            )
            _enter_tiling_back_mode(bot, ore_pos, force_core_return=True)
            return True
        ore_key = (ore_pos.x, ore_pos.y)
        bot.claimed_harvesters.add(ore_key)
        bot.logger.log(
            f"Harvester at {ore_pos} already has {adjacent_friendly_conveyors} adjacent conveyor(s), marked as claimed"
        )
        # Don't switch to TILING_BACK, we stay in FINDING_ORE mode
        return False

    # Not connected, proceed with TILING_BACK mode
    _enter_tiling_back_mode(bot, ore_pos)
    return True


def _handle_existing_harvester(bot, ct: Controller, ore_pos: Position) -> bool:
    """Handles an already-built harvester at ore_pos.

    Returns True when this helper consumed the turn decision.
    """
    building_id = ct.get_tile_building_id(ore_pos)
    if building_id is None or ct.get_entity_type(building_id) != EntityType.HARVESTER:
        return False

    ore_key = (ore_pos.x, ore_pos.y)
    if _has_adjacent_conveyor(bot, ct, ore_pos):
        bot.claimed_harvesters.add(ore_key)
        bot.logger.log(
            f"harvester already built and connected at {ore_pos}, marking claimed"
        )
        return True

    bot.logger.log(
        f"harvester already built but unclaimed at {ore_pos}, switching to tiling back"
    )
    _enter_tiling_back_mode(bot, ore_pos)
    return True


def _share_ore_marker(bot, ct: Controller, ore_pos: Position):
    ore_key = (ore_pos.x, ore_pos.y)
    if ore_key in bot.shared_ore_positions:
        return

    marker_value = marker.create_ore_marker(
        ore_pos, ct.get_current_round(), ct.get_map_width(), ct.get_map_height()
    )
    if utils.place_marker_around(ct, ct.get_position(), marker_value):
        bot.shared_ore_positions.add(ore_key)
        bot.logger.log(f"Shared ore marker for {ore_pos}")


CLAIMED_HARVESTER_RECHECK_INTERVAL = 8


def _recheck_claimed_harvesters(bot, ct: Controller):
    """Unclaim harvesters whose conveyor routes have been destroyed.
    This allows builders to re-tile broken routes instead of ignoring
    disconnected harvesters forever."""
    last_check = getattr(bot, "last_claimed_recheck_round", -9999)
    current_round = ct.get_current_round()
    if current_round - last_check < CLAIMED_HARVESTER_RECHECK_INTERVAL:
        return
    bot.last_claimed_recheck_round = current_round

    if not bot.claimed_harvesters:
        return

    to_unclaim = []
    for hkey in bot.claimed_harvesters:
        hpos = Position(hkey[0], hkey[1])
        if not _has_adjacent_conveyor(bot, ct, hpos):
            to_unclaim.append(hkey)

    for hkey in to_unclaim:
        bot.claimed_harvesters.discard(hkey)
        bot.logger.log(
            f"unclaimed harvester at {hkey}: route destroyed"
        )


def _find_disconnected_harvester_to_retile(bot, ct: Controller):
    """Check for nearby friendly harvesters that lost their routes.
    Re-tiling is cheaper than building a new harvester.
    Only considers harvesters that were PREVIOUSLY connected (had adjacent
    conveyors) to avoid re-tiling freshly placed ones."""
    my_team = ct.get_team()
    current_pos = ct.get_position()
    current_round = ct.get_current_round()
    best = None
    best_dist = float("inf")

    # Only look at harvesters we know were previously connected.
    known = getattr(bot, "known_harvesters", {})
    for hkey, info in known.items():
        if info.get("team") != my_team:
            continue
        # Skip if still claimed (route intact).
        if hkey in bot.claimed_harvesters:
            continue
        # Skip if never had adjacent conveyors (freshly placed, not yet tiled).
        if info.get("prev_adjacent_conveyors", 0) <= 0:
            continue
        if _is_ore_temporarily_blocked(bot, Position(hkey[0], hkey[1]), current_round):
            continue
        # Verify it's actually disconnected now.
        if _has_adjacent_conveyor(bot, ct, Position(hkey[0], hkey[1])):
            continue
        dist = abs(current_pos.x - hkey[0]) + abs(current_pos.y - hkey[1])
        if dist < best_dist:
            best_dist = dist
            best = hkey

    return best


def execute(bot, ct: Controller):
    _refresh_ore_target_blacklist(bot, ct.get_current_round())
    _recheck_claimed_harvesters(bot, ct)

    # Priority: re-tile disconnected friendly harvesters before finding new ore.
    retile_target = _find_disconnected_harvester_to_retile(bot, ct)
    if retile_target is not None:
        retile_pos = Position(retile_target[0], retile_target[1])
        bot.logger.log(f"priority re-tile: disconnected harvester at {retile_pos}")
        enter_tiling_back_from_origin(bot, retile_pos, origin_kind="HARVESTER")
        return

    target_data = _find_best_ore_target(bot, ct)

    if target_data is not None:
        pos, closest_pos, _ = target_data
        _share_ore_marker(bot, ct, pos)

        # 1. Are we adjacent to the ore? Build Harvester.
        if utils.manhattan(pos, ct.get_position()) == 1:
            if ct.can_build_harvester(pos):
                switched_to_tiling_back = _build_harvester_and_switch_mode(bot, ct, pos)
                # If harvester was already connected, continue finding ore instead of returning
                if switched_to_tiling_back:
                    return
                # Otherwise, fallback to finding another ore
            elif _handle_existing_harvester(bot, ct, pos):
                return
            else:
                bot.logger.log(
                    f"standing on ore at {pos}, trying to build harvester, {ct.get_global_resources()}/{ct.get_harvester_cost()}"
                )
            return

        # 2. Check resources before committing to movement.
        # if (
        #     ct.get_global_resources()[0] < ct.get_harvester_cost()[0]
        #     or ct.get_global_resources()[0] < ct.get_conveyor_cost()[0]
        # ):
        #     utils.move_random(ct)  # random move to prevent blocking
        #     bot.logger.log(
        #         f"don't find more ores when resources are low: {ct.get_global_resources()[0]}"
        #     )
        #     return

        # 3. Move toward the ore.
        bot.logger.log(f"moving toward ore access tile {closest_pos} for ore at {pos}")
        moved = navigation.move_towards(bot, ct, closest_pos)
        progress_made = moved and not navigation.consume_shared_progress_stall(bot)
        _note_ore_target_progress(
            bot,
            ct,
            pos,
            closest_pos,
            moved=progress_made,
        )
        return

    # Fallback if no target is found
    _reset_ore_target_state(bot)
    bot.builder_mode = BuilderMode.EXPLORING
    mode_exploring.execute(bot, ct)
