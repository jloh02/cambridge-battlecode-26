from cambc import (
    Controller,
    Direction,
    EntityType,
    Position,
    Environment,
    GameConstants,
)

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]
