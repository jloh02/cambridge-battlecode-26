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


def _find_best_ore_target(bot, ct: Controller, max_bfs_nodes=300):
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
                if _is_ore_claimed_by_friend(bot, neighbor, dist):
                    continue
                return (neighbor, current, dist)

            # Standard expansion
            if n_tuple not in visited and n_tuple not in known_obstacles:
                # Optional: You can add a quick check against your bot.grid here
                # to ensure the tile doesn't have an impassable building.
                visited.add(n_tuple)
                queue.append((neighbor, dist + 1))

    # 2. Fallback: If BFS maxes out (meaning the nearest ore is very far),
    # fall back to your existing Euclidean heuristic logic.
    return _find_best_ore_target_euclidean(bot, ct)


def _is_ore_claimed_by_friend(bot, ore_pos: Position, my_dist: int) -> bool:
    """Quick check to prevent two bots targeting the same nearby ore."""
    # If you have a marker-based claiming system, check it here!
    # Otherwise, do a quick proximity check of friendly bots.
    for bot_pos_tuple in bot.bot_locations:
        # If a friend is within 3 tiles of the ore, let them have it
        if abs(bot_pos_tuple[0] - ore_pos.x) + abs(bot_pos_tuple[1] - ore_pos.y) <= 3:
            return True
    return False


def _find_best_ore_target(bot, ct: Controller, max_bfs_nodes=300):
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
                if _is_ore_claimed_by_friend(bot, neighbor, dist):
                    continue
                return (neighbor, current, dist)

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

    can_target_ore = []
    for pos in utils.get_eligible_ore_locations(bot, ct):
        closest_pos = utils.closest_non_obstacle_cardinal_point_on_grid(
            bot, pos, ct.get_position()
        )
        if closest_pos is None:
            continue  # No valid adjacent position to target this ore
        d = ct.get_position().distance_squared(closest_pos)

        # Ensure no other friendly bot is closer
        if all(
            d
            <= _tuple_to_pos(bot_pos).distance_squared(
                utils.closest_non_obstacle_cardinal_point_on_grid(
                    bot, pos, _tuple_to_pos(bot_pos)
                )
            )
            for bot_pos in bot.bot_locations
            if utils.closest_non_obstacle_cardinal_point_on_grid(
                bot, pos, _tuple_to_pos(bot_pos)
            )
            is not None
        ):
            can_target_ore.append((pos, closest_pos, d))

    if not can_target_ore:
        return None

    can_target_ore.sort(key=lambda x: x[1])
    return min(
        can_target_ore, key=lambda x: x[2]
    )  # Returns (pos, closest_pos, distance)


def _is_ore_claimed_by_friend(bot, ore_pos: Position, my_dist: int) -> bool:
    """Quick check to prevent two bots targeting the same nearby ore."""
    # If you have a marker-based claiming system, check it here!
    # Otherwise, do a quick proximity check of friendly bots.
    for bot_pos_tuple in bot.bot_locations:
        # If a friend is within 3 tiles of the ore, let them have it
        if abs(bot_pos_tuple[0] - ore_pos.x) + abs(bot_pos_tuple[1] - ore_pos.y) <= 3:
            return True
    return False


def _determine_return_target(bot, start_pos):
    """Calculates whether returning to the core or a nearby conveyor is more efficient."""
    visible_candidates = list(bot.connected_friendly_conveyors)
    best_target = utils.closest_point_on_grid(bot.core_pos, start_pos)
    best_dist = utils.manhattan(start_pos, best_target)
    best_kind = TargetKind.CORE

    if visible_candidates:
        nearest_c_tuple = min(
            visible_candidates,
            key=lambda c_pos: abs(start_pos.x - c_pos[0]) + abs(start_pos.y - c_pos[1]),
        )
        nearest_c = Position(nearest_c_tuple[0], nearest_c_tuple[1])
        nearest_c_dist = utils.manhattan(start_pos, nearest_c)
        if nearest_c_dist < best_dist:
            best_target = nearest_c
            best_dist = nearest_c_dist
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

    # bot.bugnav_state = {"bugging": False, "side": 1, "start_dist": float("inf")}
    bot.pathfinding_state["path"] = []
    bot.pathfinding_state["temporary_obstacles"] = {}
    bot.pathfinding_state["tiling_back_wait_turns"] = 0
    bot.explore_target_chunk = None
    bot.explore_target_pos = None

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
        bot.logger.log(f"moving towards ore at {pos}, closest: {closest_pos}")
        navigation.move_towards(bot, ct, closest_pos)
        return

    # Fallback if no target is found
    bot.builder_mode = BuilderMode.EXPLORING
    mode_exploring.execute(bot, ct)
