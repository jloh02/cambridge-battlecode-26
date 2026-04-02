"""Helpers for symmetry-guided enemy-core scouting."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from cambc import Direction, Position

from bots.policy_fsm_v3.runtime.nav import (
    CARDINAL_DIRECTIONS,
    is_traversable_for_planning,
    manhattan_distance,
    reconstruct_path,
    unknown_neighbor_count,
)
from bots.policy_fsm_v3.runtime.sense import TurnContext


SCOUT_DIRECTIONS = (
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
)
ASSAULT_SCOUT_SLOTS = {0, 1}
STEP_BY_DIRECTION = {
    Direction.NORTH: (0, -1),
    Direction.NORTHEAST: (1, -1),
    Direction.EAST: (1, 0),
    Direction.SOUTHEAST: (1, 1),
    Direction.SOUTH: (0, 1),
    Direction.SOUTHWEST: (-1, 1),
    Direction.WEST: (-1, 0),
    Direction.NORTHWEST: (-1, -1),
}


@dataclass(frozen=True, slots=True)
class EnemyBaseScoutPlan:
    direction: Direction
    target: Position
    path: list[Position]


def scout_slot(entity_id: int) -> int:
    return entity_id % len(SCOUT_DIRECTIONS)


def scout_direction(entity_id: int) -> Direction:
    return SCOUT_DIRECTIONS[scout_slot(entity_id)]


def is_assault_scout(entity_id: int) -> bool:
    return scout_slot(entity_id) in ASSAULT_SCOUT_SLOTS


def position_with_step(position: Position, direction: Direction, steps: int = 1) -> Position:
    dx, dy = STEP_BY_DIRECTION[direction]
    return Position(position.x + (dx * steps), position.y + (dy * steps))


def clamp_to_map(position: Position, *, map_width: int, map_height: int) -> Position:
    return Position(
        min(max(position.x, 0), map_width - 1),
        min(max(position.y, 0), map_height - 1),
    )


def scout_target_for_direction(
    enemy_anchor: Position,
    *,
    map_width: int,
    map_height: int,
    direction: Direction,
) -> Position:
    # Spread the scouts around the predicted enemy core so they do not all
    # tunnel into the same visible corridor.
    return clamp_to_map(
        position_with_step(enemy_anchor, direction, 3),
        map_width=map_width,
        map_height=map_height,
    )


def find_visible_path_toward_enemy_base(
    context: TurnContext,
    *,
    start: Position,
    target: Position,
    max_nodes: int = 160,
) -> list[Position]:
    queue: deque[tuple[Position, int]] = deque([(start, 0)])
    predecessors: dict[Position, Position | None] = {start: None}
    best = start
    best_score = (
        manhattan_distance(start, target),
        0,
        0,
        start.x,
        start.y,
    )
    explored = 0

    while queue and explored < max_nodes:
        position, depth = queue.popleft()
        explored += 1
        score = (
            manhattan_distance(position, target),
            -unknown_neighbor_count(context, position),
            depth,
            position.x,
            position.y,
        )
        if score < best_score:
            best = position
            best_score = score
        for direction in CARDINAL_DIRECTIONS:
            candidate = position.add(direction)
            if candidate in predecessors:
                continue
            tile = context.tiles.get(candidate)
            if not is_traversable_for_planning(tile):
                continue
            predecessors[candidate] = position
            queue.append((candidate, depth + 1))

    if best == start:
        return []
    return reconstruct_path(predecessors, best)


def build_enemy_base_scout_plan(
    context: TurnContext,
    *,
    enemy_anchor: Position,
) -> EnemyBaseScoutPlan:
    direction = scout_direction(context.entity_id)
    target = scout_target_for_direction(
        enemy_anchor,
        map_width=context.map_width,
        map_height=context.map_height,
        direction=direction,
    )
    path = find_visible_path_toward_enemy_base(
        context,
        start=context.position,
        target=target,
    )
    return EnemyBaseScoutPlan(direction=direction, target=target, path=path)
