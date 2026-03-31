import random
import math
import os
from cambc import Controller, Direction, EntityType, Environment, Position

DEBUG = os.getenv("DEBUG", "False").lower() == "true"

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


def closest_point_on_grid(target_pos: Position, from_pos: Position) -> Position:
    return Position(
        max(target_pos.x - 1, min(from_pos.x, target_pos.x + 1)),
        max(target_pos.y - 1, min(from_pos.y, target_pos.y + 1)),
    )


def closest_non_obstacle_cardinal_point_on_grid(
    bot, target_pos: Position, from_pos: Position
) -> Position:
    known_obstacles = bot.pathfinding_state["known_obstacles"]
    closest_point = closest_point_on_grid(target_pos, from_pos)

    candidate = Position(closest_point.x, target_pos.y)
    if (
        candidate not in known_obstacles
        and bot.grid.get((candidate.x, candidate.y), {}).get("env")
        not in DO_NOT_BUILD_ON
    ):
        return candidate

    alt_candidate = Position(target_pos.x, closest_point.y)
    if (
        alt_candidate not in known_obstacles
        and bot.grid.get((alt_candidate.x, alt_candidate.y), {}).get("env")
        not in DO_NOT_BUILD_ON
    ):
        return alt_candidate

    # no choice, check further directions
    for d in CARDINAL_DIRECTIONS:
        neighbor = target_pos.add(d)
        if neighbor not in known_obstacles:
            return neighbor

    return None


def move_random(ct: Controller):
    random_dirs = DIRECTIONS[:]
    random.shuffle(random_dirs)
    for d in random_dirs:
        if ct.can_move(d):
            ct.move(d)
            break


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
            EntityType.ARMOURED_CONVEYOR,
            EntityType.MARKER,
        }:
            return True

    return False


def is_passable(ct: Controller, current_pos: Position, direction: Direction) -> bool:
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
        EntityType.ARMOURED_CONVEYOR,
        EntityType.MARKER,
        EntityType.CORE,
        None,
    ]

    if has_blocking_building:
        return False

    has_blocking_wall = ct.get_tile_env(target_pos) != Environment.EMPTY
    if has_blocking_wall:
        return False

    return True


def get_tile_building_entity_type(ct: Controller, pos: Position):
    building_id = ct.get_tile_building_id(pos)
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
