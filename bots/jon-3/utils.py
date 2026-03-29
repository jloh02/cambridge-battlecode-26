import random
import math
from cambc import Controller, Direction, EntityType, Environment, Position

# Shared Constants
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    d
    for d in DIRECTIONS
    if abs(Position(0, 0).add(d).x) + abs(Position(0, 0).add(d).y) == 1
]
DIAGONAL_DIRECTIONS = [d for d in DIRECTIONS if d not in CARDINAL_DIRECTIONS]


# Shared spatial helper functions
def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def closest_point_on_grid(target_pos: Position, from_pos: Position) -> Position:
    return Position(
        max(target_pos.x - 1, min(from_pos.x, target_pos.x + 1)),
        max(target_pos.y - 1, min(from_pos.y, target_pos.y + 1)),
    )


def closest_cardinal_point_on_grid(
    target_pos: Position, from_pos: Position
) -> Position:
    closest_point = closest_point_on_grid(target_pos, from_pos)
    if closest_point.direction_to(target_pos) not in CARDINAL_DIRECTIONS:
        return Position(closest_point.x, target_pos.y)
    return closest_point


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
