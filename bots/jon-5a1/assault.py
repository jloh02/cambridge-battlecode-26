from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from cambc import Direction, EntityType, Position


ALL_EIGHT_DIRECTIONS = (
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
)
CARDINAL_DIRECTIONS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)
DIAGONAL_DIRECTIONS = (
    Direction.NORTHEAST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
    Direction.NORTHWEST,
)
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
CONNECTED_LOGISTICS_TYPES = {
    EntityType.HARVESTER,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.FOUNDRY,
}
TURRET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}


@dataclass(frozen=True, slots=True)
class VisibleEnemy:
    position: Position
    entity_type: EntityType
    direction: Direction | None = None


@dataclass(frozen=True, slots=True)
class SiteTarget:
    position: Position
    entity_type: EntityType
    priority: int


@dataclass(frozen=True, slots=True)
class AssaultSite:
    harvester_position: Position
    ring_position: Position
    sentinel_direction: Direction
    target: SiteTarget
    cluster_size: int


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def is_in_bounds(position: Position, map_width: int, map_height: int) -> bool:
    return 0 <= position.x < map_width and 0 <= position.y < map_height


def sentinel_attack_tiles(origin: Position, direction: Direction, *, max_range_sq: int = 32) -> set[Position]:
    attackable: set[Position] = set()
    dx, dy = STEP_BY_DIRECTION[direction]
    for step in range(1, 7):
        base = Position(origin.x + (dx * step), origin.y + (dy * step))
        if (base.x - origin.x) ** 2 + (base.y - origin.y) ** 2 > max_range_sq:
            break
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                candidate = Position(base.x + ox, base.y + oy)
                rel_x = candidate.x - origin.x
                rel_y = candidate.y - origin.y
                if rel_x == 0 and rel_y == 0:
                    continue
                if rel_x * dx + rel_y * dy <= 0:
                    continue
                if (rel_x * rel_x) + (rel_y * rel_y) > max_range_sq:
                    continue
                attackable.add(candidate)
    return attackable


def can_feed_sentinel(anchor_harvester: Position, ring_position: Position, sentinel_direction: Direction) -> bool:
    feed_direction = ring_position.direction_to(anchor_harvester)
    if feed_direction not in CARDINAL_DIRECTIONS:
        return False
    if sentinel_direction in DIAGONAL_DIRECTIONS:
        return True
    return feed_direction != sentinel_direction


def connected_enemy_logistics_cluster(anchor_harvester: Position, enemies: list[VisibleEnemy]) -> set[Position]:
    logistics_positions = {
        enemy.position
        for enemy in enemies
        if enemy.entity_type in CONNECTED_LOGISTICS_TYPES
    }
    if anchor_harvester not in logistics_positions:
        return set()

    visited: set[Position] = set()
    queue: deque[Position] = deque([anchor_harvester])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for direction in CARDINAL_DIRECTIONS:
            candidate = current.add(direction)
            if candidate in logistics_positions and candidate not in visited:
                queue.append(candidate)

    return visited


def _target_priority(
    enemy: VisibleEnemy,
    *,
    anchor_harvester: Position,
    cluster_positions: set[Position],
) -> int | None:
    if enemy.entity_type in TURRET_TYPES:
        return 0
    if enemy.position == anchor_harvester:
        return None
    if enemy.position in cluster_positions:
        return 1
    if enemy.entity_type == EntityType.CORE:
        return 2
    return None


def choose_best_site_for_harvester(
    *,
    harvester_position: Position,
    current_position: Position,
    enemies: list[VisibleEnemy],
    map_width: int,
    map_height: int,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
) -> AssaultSite | None:
    blocked = blocked_ring_positions or set()
    cluster_positions = connected_enemy_logistics_cluster(harvester_position, enemies)
    best: tuple[tuple[int, int, int, int, int, int], AssaultSite] | None = None

    for site_direction in CARDINAL_DIRECTIONS:
        ring_position = harvester_position.add(site_direction)
        if ring_position in blocked:
            continue
        if not is_in_bounds(ring_position, map_width, map_height):
            continue
        for direction_index, sentinel_direction in enumerate(ALL_EIGHT_DIRECTIONS):
            if not can_feed_sentinel(harvester_position, ring_position, sentinel_direction):
                continue
            attack_tiles = sentinel_attack_tiles(ring_position, sentinel_direction)
            best_target: tuple[tuple[int, int, int, int], SiteTarget] | None = None
            for enemy in enemies:
                if enemy.position not in attack_tiles:
                    continue
                priority = _target_priority(
                    enemy,
                    anchor_harvester=harvester_position,
                    cluster_positions=cluster_positions,
                )
                if priority is None:
                    continue
                if legal_fire_fn is not None and not legal_fire_fn(ring_position, sentinel_direction, enemy.position):
                    continue
                subpriority = 0 if enemy.entity_type == EntityType.HARVESTER else 1
                target_score = (
                    priority,
                    subpriority,
                    manhattan(ring_position, enemy.position),
                    enemy.position.x + (enemy.position.y * map_width),
                )
                target = SiteTarget(enemy.position, enemy.entity_type, priority)
                if best_target is None or target_score < best_target[0]:
                    best_target = (target_score, target)
            if best_target is None:
                continue
            site = AssaultSite(
                harvester_position=harvester_position,
                ring_position=ring_position,
                sentinel_direction=sentinel_direction,
                target=best_target[1],
                cluster_size=len(cluster_positions),
            )
            site_score = (
                best_target[0][0],
                manhattan(current_position, ring_position),
                -len(cluster_positions),
                best_target[0][1],
                direction_index,
                ring_position.x + (ring_position.y * map_width),
            )
            if best is None or site_score < best[0]:
                best = (site_score, site)

    return best[1] if best is not None else None


def choose_best_assault_site(
    *,
    current_position: Position,
    enemies: list[VisibleEnemy],
    map_width: int,
    map_height: int,
    blocked_ring_positions: set[Position] | None = None,
    legal_fire_fn=None,
) -> AssaultSite | None:
    best: tuple[tuple[int, int, int, int], AssaultSite] | None = None

    for enemy in enemies:
        if enemy.entity_type != EntityType.HARVESTER:
            continue
        site = choose_best_site_for_harvester(
            harvester_position=enemy.position,
            current_position=current_position,
            enemies=enemies,
            map_width=map_width,
            map_height=map_height,
            blocked_ring_positions=blocked_ring_positions,
            legal_fire_fn=legal_fire_fn,
        )
        if site is None:
            continue
        score = (
            site.target.priority,
            manhattan(current_position, site.ring_position),
            -site.cluster_size,
            enemy.position.x + (enemy.position.y * map_width),
        )
        if best is None or score < best[0]:
            best = (score, site)

    return best[1] if best is not None else None
