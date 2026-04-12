import random
import math
import os
from cambc import Controller, Direction, EntityType, Environment, Position

DEBUG = os.getenv("DEBUG", "False").lower() == "true"
DEBUG_TURN_PROFILE = (
    os.getenv("DEBUG_TURN_PROFILE", os.getenv("DEBUG_ASSAULT_PROFILE", "False")).lower()
    == "true"
)
DEBUG_ASSAULT_PROFILE = DEBUG_TURN_PROFILE
TURN_PROFILE_THRESHOLD_NS = int(
    os.getenv("TURN_PROFILE_THRESHOLD_NS", os.getenv("ASSAULT_PROFILE_THRESHOLD_NS", "900000"))
)
ASSAULT_PROFILE_THRESHOLD_NS = TURN_PROFILE_THRESHOLD_NS

# Shared Constants
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    d
    for d in DIRECTIONS
    if abs(Position(0, 0).add(d).x) + abs(Position(0, 0).add(d).y) == 1
]
DIAGONAL_DIRECTIONS = [d for d in DIRECTIONS if d not in CARDINAL_DIRECTIONS]

DO_NOT_BUILD_ON = {
    Environment.ORE_AXIONITE,
    Environment.ORE_TITANIUM,
    Environment.WALL,
}

DIRECT_CORE_RETURN_MAX_DIST = 18

# TODO get axionite refinery logic done first
def get_eligible_ore_locations(bot, ct: Controller):
    """Determines which ore locations are worth targeting based on current resources."""
    # if (
    #     ct.get_global_resources()[0] >= MINIMUM_RESOURCE_TO_MINE_AXIONITE
    #     or ct.get_current_round() >= MINIMUM_AXIONITE_ROUND
    # ):
    #     return list(bot.titanium_locations) + list(bot.axionite_locations)
    # else:
    return list(bot.titanium_locations)


# Shared spatial helper functions
def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def closest_point_near_target(
    target_pos: Position,
    from_pos: Position,
    *,
    max_distance_sq: int | None = None,
    max_chebyshev: int | None = None,
    cardinal_only: bool = False,
    include_target: bool = False,
    is_valid=None,
) -> Position | None:
    """Find the nearest candidate around target_pos subject to geometric toggles.

    Use max_chebyshev for square neighborhoods (e.g. 3x3), and max_distance_sq
    for circular neighborhoods (e.g. action radius). Both can be combined.
    """
    if max_distance_sq is None and max_chebyshev is None:
        raise ValueError("closest_point_near_target needs a search bound")

    search_radius = 0
    if max_chebyshev is not None:
        search_radius = max(search_radius, max_chebyshev)
    if max_distance_sq is not None:
        search_radius = max(search_radius, int(math.sqrt(max_distance_sq)) + 1)

    best_pos = None
    best_dist_sq = None

    for dx in range(-search_radius, search_radius + 1):
        for dy in range(-search_radius, search_radius + 1):
            if dx == 0 and dy == 0 and not include_target:
                continue

            if cardinal_only and abs(dx) + abs(dy) != 1:
                continue

            if max_chebyshev is not None and max(abs(dx), abs(dy)) > max_chebyshev:
                continue

            if max_distance_sq is not None and dx * dx + dy * dy > max_distance_sq:
                continue

            pos = Position(target_pos.x + dx, target_pos.y + dy)
            if is_valid is not None and not is_valid(pos):
                continue

            dist_sq = (from_pos.x - pos.x) ** 2 + (from_pos.y - pos.y) ** 2
            if best_dist_sq is None or dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_pos = pos

    return best_pos


def closest_point_on_grid(target_pos: Position, from_pos: Position) -> Position:
    best_pos = closest_point_near_target(
        target_pos,
        from_pos,
        max_chebyshev=1,
        include_target=True,
    )
    if best_pos is None:
        return target_pos
    return best_pos


def core_return_distance(core_pos: Position | None, from_pos: Position) -> int:
    if core_pos is None:
        return 10**9
    return manhattan(from_pos, closest_point_on_grid(core_pos, from_pos))


def should_prioritize_direct_core_return(
    core_pos: Position | None,
    from_pos: Position,
    *,
    max_dist: int = DIRECT_CORE_RETURN_MAX_DIST,
) -> bool:
    return core_return_distance(core_pos, from_pos) <= max_dist


def closest_non_obstacle_cardinal_point_on_grid(
    bot, ct: Controller, target_pos: Position, from_pos: Position
) -> Position:
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    map_w = ct.get_map_width()
    map_h = ct.get_map_height()

    def is_valid(pos: Position) -> bool:
        if not (0 <= pos.x < map_w and 0 <= pos.y < map_h):
            return False

        c_tuple = (pos.x, pos.y)
        if c_tuple in known_obstacles:
            return False

        tile_data = bot.grid.get(c_tuple)
        if tile_data is not None and tile_data.get("env") in DO_NOT_BUILD_ON:
            return False

        return True

    # Same strategy as `jon-5`, cheaper execution: keep this helper single-pass
    # so ore selection does not allocate candidate lists on every comparison.
    return closest_point_near_target(
        target_pos,
        from_pos,
        max_distance_sq=2,
        cardinal_only=True,
        include_target=False,
        is_valid=is_valid,
    )


def move_random(ct: Controller):
    random_dirs = DIRECTIONS[:]
    random.shuffle(random_dirs)
    for d in random_dirs:
        if ct.can_move(d):
            ct.move(d)
            break


def bump_profile(bot, key: str, value: int = 1) -> None:
    profile = getattr(bot, "turn_profile", None)
    if profile is None:
        return
    profile[key] = profile.get(key, 0) + value


def max_profile(bot, key: str, value: int) -> None:
    profile = getattr(bot, "turn_profile", None)
    if profile is None:
        return
    profile[key] = max(profile.get(key, value), value)


def set_profile(bot, key: str, value) -> None:
    profile = getattr(bot, "turn_profile", None)
    if profile is None:
        return
    profile[key] = value


def in_bounds(ct: Controller, pos: Position) -> bool:
    return 0 <= pos.x < ct.get_map_width() and 0 <= pos.y < ct.get_map_height()


def distance_to_line(p, start, target) -> float:
    """Calculates the shortest distance from point p to the line intersecting start and target."""
    # Using the standard point-to-line distance formula
    numerator = abs(
        (target.x - start.x) * (start.y - p.y) - (start.x - p.x) * (target.y - start.y)
    )
    denominator = math.sqrt((target.x - start.x) ** 2 + (target.y - start.y) ** 2)

    if denominator == 0:
        return 0.0  # Start and target are exactly the same

    return numerator / denominator


def is_disallowed_to_build_on(bot, ct: Controller, pos: Position) -> bool:
    """Checks if building is disallowed on the given position."""
    pos_tuple = (pos.x, pos.y)
    if bot.grid.get(pos_tuple) is None:
        return False

    entv = bot.grid[pos_tuple].get("entity")
    if entv is not None and entv in DO_NOT_BUILD_ON:
        return True

    b_type = bot.grid[pos_tuple].get("building")
    if b_type is not None:
        if b_type not in {
            EntityType.ROAD,
            EntityType.CONVEYOR,
            EntityType.SPLITTER,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.MARKER,
        }:
            return True

    return False


def is_position_passable_from_grid(
    bot,
    ct: Controller,
    pos: Position,
    *,
    require_visible_this_round: bool = False,
) -> bool:
    """Perception-backed passability check using bot.grid state.

    This avoids direct tile queries and is intended for decision heuristics
    (for example, selecting a heal anchor) after perception has refreshed.
    """
    if not in_bounds(ct, pos):
        return False

    tile_data = bot.grid.get((pos.x, pos.y))
    if tile_data is None:
        return False

    if require_visible_this_round:
        if tile_data.get("last_seen") != ct.get_current_round():
            return False

    env = tile_data.get("env")
    if env in DO_NOT_BUILD_ON:
        return False

    building = tile_data.get("building")
    if building not in {
        None,
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.MARKER,
        EntityType.CORE,
    }:
        return False

    if building == EntityType.CORE and tile_data.get("building_team") != ct.get_team():
        return False

    entity = tile_data.get("entity")
    if entity is not None:
        if entity != EntityType.BUILDER_BOT:
            return False

        occupying_bot_id = tile_data.get("id")
        if occupying_bot_id is not None and occupying_bot_id != ct.get_id():
            return False

    return True


def is_passable(
    bot, ct: Controller, current_pos: Position, direction: Direction
) -> bool:
    target_pos = current_pos.add(direction)

    if not in_bounds(ct, target_pos):
        return False

    # if ct.can_move(direction):
    #     return True

    # Safely get entity type only if building exists
    building_et = get_tile_building_entity_type(ct, target_pos)

    has_blocking_building = building_et not in [
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.MARKER,
        EntityType.CORE,
        None,
    ]

    if has_blocking_building:
        return False

    if building_et == EntityType.CORE:
        target_cell = bot.grid.get((target_pos.x, target_pos.y))
        target_team = target_cell.get("entity_team") if target_cell is not None else None
        if target_team != ct.get_team():
            return False

    has_blocking_wall = ct.get_tile_env(target_pos) != Environment.EMPTY
    if has_blocking_wall:
        return False

    return True


def get_tile_building_entity_type(ct: Controller, pos: Position):
    get_tile_building_id = getattr(ct, "get_tile_building_id", None)
    if get_tile_building_id is None:
        return None

    building_id = get_tile_building_id(pos)
    if building_id is not None:
        return ct.get_entity_type(building_id)
    return None


def destroy_marker_if_present(ct: Controller, pos: Position) -> bool:
    if get_tile_building_entity_type(ct, pos) != EntityType.MARKER:
        return False

    if ct.can_destroy(pos):
        ct.destroy(pos)
        return True

    return False


def direction_toward(from_pos: Position, to_pos: Position) -> Direction:
    dx = to_pos.x - from_pos.x
    dy = to_pos.y - from_pos.y

    if dx == 0 and dy == 0:
        return CARDINAL_DIRECTIONS[0]

    best_dir = None
    best_dot = -float("inf")
    for direction in DIRECTIONS:
        ddx, ddy = direction.delta()
        dot = dx * ddx + dy * ddy
        if dot > best_dot:
            best_dot = dot
            best_dir = direction

    return best_dir


def place_marker_around(
    ct: Controller,
    origin_pos: Position,
    marker_value: int,
    directions: list[Direction] | None = None,
) -> bool:
    # Markers occupy tiles and block conveyor/building construction.
    # Re-enabling this naively caused massive regression (41.7% from 65%).
    # Needs careful design: only place markers on non-construction tiles.
    return False


def place_assault_marker_around(
    ct: Controller,
    origin_pos: Position,
    marker_value: int,
    directions: list[Direction] | None = None,
) -> bool:
    for direction in directions or DIRECTIONS:
        marker_pos = origin_pos.add(direction)
        if ct.can_place_marker(marker_pos):
            ct.place_marker(marker_pos, marker_value)
            return True

    return False


def place_connected_harvester_marker_around(
    ct: Controller,
    origin_pos: Position,
    marker_value: int,
    directions: list[Direction] | None = None,
) -> bool:
    for direction in directions or DIRECTIONS:
        marker_pos = origin_pos.add(direction)
        if ct.can_place_marker(marker_pos):
            ct.place_marker(marker_pos, marker_value)
            return True

    return False
