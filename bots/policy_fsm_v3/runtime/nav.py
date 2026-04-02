"""Small pathing and spatial helpers.

The MVP code intentionally favors readable, bounded searches over deeply tuned
 navigation. These helpers are used both by the bots and by unit tests.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from cambc import Direction, EntityType, Environment, Position

from .sense import TileInfo, TurnContext


CARDINAL_DIRECTIONS = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]
ALL_DIRECTIONS = [direction for direction in Direction if direction != Direction.CENTRE]


@dataclass(frozen=True, slots=True)
class VisibleOreLaneConfig:
    max_nodes: int = 600
    path_length_weight: float = 1.0
    workable_adjacent_weight: float = 2.0
    anchor_distance_weight: float = 0.35
    repetition_penalty_weight: float = 1.0
    claimant_penalty_weight: float = 2.0
    boundary_penalty_weight: float = 1.4


@dataclass(frozen=True, slots=True)
class VisibleOreLaneChoice:
    ore_position: Position
    goal_position: Position
    path: list[Position]
    score: float
    workable_adjacent_tiles: int
    claimant_count: int
    boundary_penalty: float


DEFAULT_VISIBLE_ORE_LANE_CONFIG = VisibleOreLaneConfig()


def adjacent_cardinals(position: Position) -> list[Position]:
    return [position.add(direction) for direction in CARDINAL_DIRECTIONS]


def adjacent_all(position: Position) -> list[Position]:
    return [position.add(direction) for direction in ALL_DIRECTIONS]


def manhattan_distance(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def direction_priority_toward(start: Position, goal: Position) -> list[Direction]:
    """Return cardinal directions ordered by how much they approach the goal."""

    options: list[tuple[int, Direction]] = []
    for direction in CARDINAL_DIRECTIONS:
        next_pos = start.add(direction)
        options.append((manhattan_distance(next_pos, goal), direction))
    options.sort(key=lambda item: item[0])
    return [direction for _, direction in options]


def is_buildable_empty_ground(tile: TileInfo | None) -> bool:
    """Tiles where a builder can usually place a road or conveyor."""

    if tile is None:
        return False
    if tile.environment != Environment.EMPTY:
        return False
    return tile.building_type in (None, EntityType.MARKER, EntityType.ROAD, EntityType.CONVEYOR)


def is_traversable_for_planning(tile: TileInfo | None) -> bool:
    """Approximate traversability used for human-readable planning.

    Planning treats empty ground as traversable because a builder can road-build
    onto it in the same turn. Ore and walls stay blocked because roads cannot be
    placed on them.
    """

    if tile is None:
        return False
    if tile.builder_bot_id is not None:
        return False
    if tile.environment in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
        return tile.building_type == EntityType.CORE
    if tile.building_type in (
        None,
        EntityType.MARKER,
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.CORE,
    ):
        return True
    return False


def ore_adjacent_goals(context: TurnContext, ore_position: Position) -> set[Position]:
    return {
        candidate
        for candidate in adjacent_cardinals(ore_position)
        if candidate in context.tiles
    }


def ore_adjacent_workable_tiles(context: TurnContext, ore_position: Position) -> list[Position]:
    workable: list[Position] = []
    for candidate in ore_adjacent_goals(context, ore_position):
        tile = context.tiles.get(candidate)
        if is_traversable_for_planning(tile):
            workable.append(candidate)
    return workable


def nearest_visible_ore(
    context: TurnContext,
    *,
    prefer_titanium: bool = False,
    allow_axionite: bool = True,
) -> Position | None:
    """Pick the visible ore tile that best matches the requested bias."""

    candidates: list[tuple[int, int, Position]] = []
    for position in context.visible_ore_tiles:
        tile = context.tiles[position]
        if tile.environment == Environment.ORE_AXIONITE and not allow_axionite:
            continue
        bias = 0
        if prefer_titanium and tile.environment == Environment.ORE_TITANIUM:
            bias -= 10
        candidates.append((bias, manhattan_distance(context.position, position), position))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2].x, item[2].y))
    return candidates[0][2]


def find_path_to_visible_goal(
    context: TurnContext,
    start: Position,
    goals: set[Position],
    *,
    max_nodes: int = 600,
) -> list[Position]:
    """Breadth-first search through visible tiles only.

    The result excludes the start position so callers can directly ask for the
    first next tile to step onto.
    """

    if not goals:
        return []
    if start in goals:
        return []

    queue: deque[Position] = deque([start])
    predecessors: dict[Position, Position | None] = {start: None}
    tiles = context.tiles
    explored = 0

    while queue and explored < max_nodes:
        position = queue.popleft()
        explored += 1
        for direction in CARDINAL_DIRECTIONS:
            next_pos = position.add(direction)
            if next_pos in predecessors:
                continue
            tile = tiles.get(next_pos)
            if not is_traversable_for_planning(tile):
                continue
            predecessors[next_pos] = position
            if next_pos in goals:
                return reconstruct_path(predecessors, next_pos)
            queue.append(next_pos)
    return []


def distance_to_map_edge(context: TurnContext, position: Position) -> int:
    return min(
        position.x,
        position.y,
        max(context.map_width - 1 - position.x, 0),
        max(context.map_height - 1 - position.y, 0),
    )


def _boundary_trap_penalty(context: TurnContext, ore_position: Position, workable_adjacent_tiles: int) -> float:
    edge_distance = distance_to_map_edge(context, ore_position)
    penalty = max(0, 2 - edge_distance)
    if workable_adjacent_tiles <= 1:
        penalty += 1
    return float(penalty)


def find_best_visible_ore_lane(
    context: TurnContext,
    start: Position,
    ore_positions: list[Position] | set[Position],
    config: VisibleOreLaneConfig = DEFAULT_VISIBLE_ORE_LANE_CONFIG,
    *,
    anchor_position: Position | None = None,
    claimant_counts: dict[Position, int] | None = None,
    repetition_penalties: dict[Position, float] | None = None,
    blocked_ores: set[Position] | None = None,
) -> VisibleOreLaneChoice | None:
    best: VisibleOreLaneChoice | None = None
    claimants = claimant_counts or {}
    penalties = repetition_penalties or {}
    blocked = blocked_ores or set()

    for ore_position in ore_positions:
        if ore_position in blocked:
            continue
        ore_tile = context.tiles.get(ore_position)
        if ore_tile is None or ore_tile.environment not in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            continue
        goals = ore_adjacent_goals(context, ore_position)
        if not goals:
            continue
        path = find_path_to_visible_goal(context, start, goals, max_nodes=config.max_nodes)
        if not path and start not in goals:
            continue
        goal_position = path[-1] if path else start
        workable_adjacent_tiles = len(ore_adjacent_workable_tiles(context, ore_position))
        repetition_penalty = penalties.get(goal_position, 0.0)
        claimant_count = claimants.get(ore_position, 0)
        boundary_penalty = _boundary_trap_penalty(context, ore_position, workable_adjacent_tiles)
        anchor_distance = 0
        if anchor_position is not None:
            anchor_distance = manhattan_distance(goal_position, anchor_position)
        score = 0.0
        score -= float(len(path)) * config.path_length_weight
        score += float(workable_adjacent_tiles) * config.workable_adjacent_weight
        score -= float(anchor_distance) * config.anchor_distance_weight
        score -= repetition_penalty * config.repetition_penalty_weight
        score -= float(claimant_count) * config.claimant_penalty_weight
        score -= boundary_penalty * config.boundary_penalty_weight

        choice = VisibleOreLaneChoice(
            ore_position=ore_position,
            goal_position=goal_position,
            path=path,
            score=score,
            workable_adjacent_tiles=workable_adjacent_tiles,
            claimant_count=claimant_count,
            boundary_penalty=boundary_penalty,
        )
        if best is None:
            best = choice
            continue
        if (
            choice.score,
            -len(choice.path),
            choice.ore_position.x,
            choice.ore_position.y,
        ) > (
            best.score,
            -len(best.path),
            best.ore_position.x,
            best.ore_position.y,
        ):
            best = choice
    return best


def in_bounds(context: TurnContext, position: Position) -> bool:
    return 0 <= position.x < context.map_width and 0 <= position.y < context.map_height


def unknown_neighbor_count(context: TurnContext, position: Position) -> int:
    unknown = 0
    north = position.add(Direction.NORTH)
    if in_bounds(context, north) and north not in context.tiles:
        unknown += 1
    east = position.add(Direction.EAST)
    if in_bounds(context, east) and east not in context.tiles:
        unknown += 1
    south = position.add(Direction.SOUTH)
    if in_bounds(context, south) and south not in context.tiles:
        unknown += 1
    west = position.add(Direction.WEST)
    if in_bounds(context, west) and west not in context.tiles:
        unknown += 1
    return unknown


def choose_bug_escape_step(
    context: TurnContext,
    start: Position,
    target: Position,
    *,
    recent_positions: list[Position] | tuple[Position, ...] = (),
    blocked_positions: set[Position] | None = None,
) -> Position | None:
    blocked = blocked_positions or set()
    recent_counts: dict[Position, int] | None = None
    if recent_positions:
        recent_counts = {}
        for position in recent_positions:
            recent_counts[position] = recent_counts.get(position, 0) + 1

    target_distance = manhattan_distance(start, target)
    best: tuple[float, Position] | None = None
    for direction in CARDINAL_DIRECTIONS:
        candidate = start.add(direction)
        if candidate in blocked:
            continue
        tile = context.tiles.get(candidate)
        if not is_traversable_for_planning(tile):
            continue
        candidate_distance = manhattan_distance(candidate, target)
        boundary_penalty = max(0, 1 - distance_to_map_edge(context, candidate))
        candidate_unknowns = 0
        north = candidate.add(Direction.NORTH)
        if in_bounds(context, north) and north not in context.tiles:
            candidate_unknowns += 1
        east = candidate.add(Direction.EAST)
        if in_bounds(context, east) and east not in context.tiles:
            candidate_unknowns += 1
        south = candidate.add(Direction.SOUTH)
        if in_bounds(context, south) and south not in context.tiles:
            candidate_unknowns += 1
        west = candidate.add(Direction.WEST)
        if in_bounds(context, west) and west not in context.tiles:
            candidate_unknowns += 1
        score = 0.0
        if candidate_distance < target_distance:
            score += 1.5
        score -= float(candidate_distance) * 0.3
        score -= float(recent_counts.get(candidate, 0) if recent_counts is not None else 0) * 1.2
        score -= float(boundary_penalty) * 0.8
        score += float(candidate_unknowns) * 0.4
        if best is None or (score, -candidate.x, -candidate.y) > (best[0], -best[1].x, -best[1].y):
            best = (score, candidate)
    return None if best is None else best[1]


def reconstruct_path(predecessors: dict[Position, Position | None], goal: Position) -> list[Position]:
    path: list[Position] = []
    current = goal
    while predecessors[current] is not None:
        path.append(current)
        current = predecessors[current]
    path.reverse()
    return path


def find_path_to_best_frontier(
    context: TurnContext,
    start: Position,
    *,
    blocked_positions: set[Position] | None = None,
    max_nodes: int = 600,
) -> list[Position]:
    """Find a visible path to the best exploration frontier.

    A frontier tile is any reachable visible tile that borders at least one
    unseen in-bounds cardinal neighbor. This is the core exploration primitive
    for the robust strategy family because it avoids brittle fixed-direction
    wandering on maze-like maps such as `wasteland`.
    """

    blocked_positions = blocked_positions or set()
    queue: deque[tuple[Position, int]] = deque([(start, 0)])
    predecessors: dict[Position, Position | None] = {start: None}
    best_position: Position | None = None
    best_unknown = -1
    best_depth = max_nodes + 1
    explored = 0
    tiles = context.tiles

    while queue and explored < max_nodes:
        position, current_depth = queue.popleft()
        if best_unknown == 4 and current_depth > best_depth:
            break
        explored += 1
        if position != start and position not in blocked_positions:
            unknown = 0
            north = position.add(Direction.NORTH)
            if in_bounds(context, north) and north not in context.tiles:
                unknown += 1
            east = position.add(Direction.EAST)
            if in_bounds(context, east) and east not in context.tiles:
                unknown += 1
            south = position.add(Direction.SOUTH)
            if in_bounds(context, south) and south not in context.tiles:
                unknown += 1
            west = position.add(Direction.WEST)
            if in_bounds(context, west) and west not in context.tiles:
                unknown += 1
            if unknown > 0:
                if (
                    unknown > best_unknown
                    or (
                        unknown == best_unknown
                        and (
                            current_depth < best_depth
                            or (
                                current_depth == best_depth
                                and best_position is not None
                                and (position.x, position.y) < (best_position.x, best_position.y)
                            )
                            or (current_depth == best_depth and best_position is None)
                        )
                    )
                ):
                    best_position = position
                    best_unknown = unknown
                    best_depth = current_depth
        for direction in CARDINAL_DIRECTIONS:
            next_pos = position.add(direction)
            if next_pos in predecessors:
                continue
            tile = tiles.get(next_pos)
            if not is_traversable_for_planning(tile):
                continue
            predecessors[next_pos] = position
            queue.append((next_pos, current_depth + 1))

    if best_position is None:
        return []
    return reconstruct_path(predecessors, best_position)
