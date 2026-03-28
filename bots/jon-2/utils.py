from cambc import Controller, Direction, EntityType, Environment, Position

# Shared Constants
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    d
    for d in DIRECTIONS
    if abs(Position(0, 0).add(d).x) + abs(Position(0, 0).add(d).y) == 1
]


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


def is_passable(ct: Controller, current_pos: Position, direction: Direction) -> bool:
    target_pos = current_pos.add(direction)
    if ct.can_move(direction):
        return True

    building = ct.get_tile_building_id(target_pos)
    # Safely get entity type only if building exists
    building_et = ct.get_entity_type(building) if building is not None else None

    has_blocking_building = building is not None and building_et not in [
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
    ]

    if has_blocking_building:
        return False

    has_blocking_wall = ct.get_tile_env(target_pos) != Environment.EMPTY
    if has_blocking_wall:
        return False

    return True
