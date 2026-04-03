from cambc import Controller, Position
from states import BuilderMode, TargetKind
import utils
import navigation
import mode_exploring
import marker
from collections import deque

MINIMUM_RESOURCE_TO_MINE_AXIONITE = 800
MINIMUM_AXIONITE_ROUND = 100


def _tuple_to_pos(pos_tuple: tuple[int, int]) -> Position:
    return Position(pos_tuple[0], pos_tuple[1])


def _cached_access_point(bot, ct: Controller, ore_pos, from_pos, cache: dict):
    key = (ore_pos.x, ore_pos.y, from_pos.x, from_pos.y)
    if key not in cache:
        cache[key] = utils.closest_non_obstacle_cardinal_point_on_grid(
            bot, ct, ore_pos, from_pos
        )
    return cache[key]


def _find_best_ore_target(bot, ct: Controller, max_bfs_nodes=50):
    """
    Finds the closest ore using a BFS flood-fill to account for walls and pathing.
    Falls back to Euclidean distance if the nearest ore is extremely far away.
    """
    if not bot.titanium_locations:
        return None

    start_pos = ct.get_position()
    visited = {(start_pos.x, start_pos.y)}
    queue = deque([(start_pos, 0)])

    known_obstacles = bot.pathfinding_state["known_obstacles"]
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()

    nodes_expanded = 0

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
    """Original logic: Finds the closest ore using straight-line distance."""
    if not (bot.titanium_locations or bot.axionite_locations):
        return None

    access_cache = {}
    my_pos = ct.get_position()
    best_candidate = None
    best_key = None
    for pos in utils.get_eligible_ore_locations(bot, ct):
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
        friend_access = _cached_access_point(
            bot, ct, ore_pos, friend_pos, access_cache
        )
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

    if visible_candidates:
        nearest_c_tuple, _ = min(
            visible_candidates,
            key=lambda item: (
                abs(start_pos.x - item[0][0]) + abs(start_pos.y - item[0][1])
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


def _build_harvester_and_switch_mode(bot, ct: Controller, ore_pos):
    """Handles construction and state transition when ore is reached."""
    bot.logger.log(f"building harvester {ore_pos}")
    ct.build_harvester(ore_pos)

    bot.last_harvester_pos = ore_pos
    bot.tiled_back_positions = set()
    bot.nearest_conveyor_pos = None
    bot.nearest_conveyor_dist_manhatten = float("inf")
    bot.last_return_target_refresh_round = -1

    # bot.bugnav_state = {"bugging": False, "side": 1, "start_dist": float("inf")}
    bot.pathfinding_state["path"] = []
    bot.pathfinding_state["temporary_obstacles"] = {}
    bot.pathfinding_state["tiling_back_wait_turns"] = 0
    bot.pathfinding_state["last_replan_signature"] = None
    bot.pathfinding_state["last_replan_round"] = -1
    bot.explore_target_chunk = None
    bot.explore_target_pos = None
    bot.pending_bridge_plan = None
    bot.bridge_transit_path = None
    bot.bridge_transit_cooldown_until = -1

    bot.builder_mode = BuilderMode.TILING_BACK
    _determine_return_target(bot, ore_pos)


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


def execute(bot, ct: Controller):
    target_data = _find_best_ore_target(bot, ct)

    if target_data is not None:
        pos, closest_pos, _ = target_data
        _share_ore_marker(bot, ct, pos)

        # 1. Are we adjacent to the ore? Build Harvester.
        if utils.manhattan(pos, ct.get_position()) == 1:
            if ct.can_build_harvester(pos):
                _build_harvester_and_switch_mode(bot, ct, pos)
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
        navigation.move_towards(bot, ct, closest_pos)
        return

    # Fallback if no target is found
    bot.builder_mode = BuilderMode.EXPLORING
    mode_exploring.execute(bot, ct)
