"""Compact logistics helpers shared by the higher-end policy families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from cambc import Direction, EntityType, Environment, Position, Team

from .nav import CARDINAL_DIRECTIONS, manhattan_distance
from .sense import TurnContext


@dataclass(frozen=True, slots=True)
class RouteTileSnapshot:
    building_type: EntityType | None
    building_team: Team | None
    environment: Environment | None
    direction: Direction | None
    bridge_target: Position | None
    visible: bool


class RememberedRouteTile(Protocol):
    building_type: EntityType | None
    building_team: Team | None
    environment: Environment | None
    direction: Direction | None
    bridge_target: Position | None
    last_seen_round: int


def in_bounds(context: TurnContext, position: Position) -> bool:
    return 0 <= position.x < context.map_width and 0 <= position.y < context.map_height


def segment_tile_snapshot(
    context: TurnContext,
    position: Position,
    *,
    belief_tiles: Mapping[Position, RememberedRouteTile] | None = None,
    current_round: int | None = None,
    route_memory_ttl: int = 0,
) -> RouteTileSnapshot:
    tile = context.tiles.get(position)
    if tile is not None:
        direction = None
        bridge_target = None
        if tile.building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and tile.building_id is not None:
            entity = context.entities.get(tile.building_id)
            if entity is not None:
                direction = entity.direction
                bridge_target = entity.bridge_target
        return RouteTileSnapshot(
            building_type=tile.building_type,
            building_team=tile.building_team,
            environment=tile.environment,
            direction=direction,
            bridge_target=bridge_target,
            visible=True,
        )

    if belief_tiles is None or current_round is None:
        return RouteTileSnapshot(None, None, None, None, None, False)
    belief = belief_tiles.get(position)
    if belief is None or belief.last_seen_round < current_round - route_memory_ttl:
        return RouteTileSnapshot(None, None, None, None, None, False)
    return RouteTileSnapshot(
        building_type=belief.building_type,
        building_team=belief.building_team,
        environment=belief.environment,
        direction=belief.direction,
        bridge_target=belief.bridge_target,
        visible=False,
    )


def pipeline_next_hop(context: TurnContext, position: Position) -> Position | None:
    tile = context.tiles.get(position)
    if tile is None or tile.building_team != context.team:
        return None
    if tile.building_type == EntityType.CORE:
        return position
    entity = context.entities.get(tile.building_id) if tile.building_id is not None else None
    if tile.building_type == EntityType.CONVEYOR:
        if entity is None or entity.direction is None:
            return None
        return position.add(entity.direction)
    if tile.building_type == EntityType.BRIDGE:
        if entity is None or entity.bridge_target is None:
            return None
        return entity.bridge_target
    return None


def belief_pipeline_next_hop(
    context: TurnContext,
    position: Position,
    *,
    belief_tiles: Mapping[Position, RememberedRouteTile],
    current_round: int,
    route_memory_ttl: int,
) -> Position | None:
    remembered = belief_tiles.get(position)
    if remembered is None:
        return None
    if remembered.last_seen_round < current_round - route_memory_ttl:
        return None
    if remembered.building_team != context.team:
        return None
    if remembered.building_type == EntityType.CORE:
        return position
    if remembered.building_type == EntityType.CONVEYOR:
        if remembered.direction is None:
            return None
        return position.add(remembered.direction)
    if remembered.building_type == EntityType.BRIDGE:
        return remembered.bridge_target
    return None


def trace_pipeline_sink(
    start: Position,
    *,
    next_hop,
    max_hops: int = 64,
) -> bool:
    if max_hops <= 0:
        return False
    seen: set[Position] = set()
    current = start
    for _ in range(max_hops):
        if current in seen:
            return False
        seen.add(current)
        step = next_hop(current)
        if step is None:
            return False
        if step == current:
            return True
        current = step
    return False


def bridge_target_is_valid(
    context: TurnContext,
    *,
    site: Position,
    target: Position,
    team: Team,
    actor_id: int,
    avoid: Position | None = None,
    max_squared_distance: int = 9,
) -> bool:
    if target == site:
        return False
    if avoid is not None and target == avoid:
        return False
    if not in_bounds(context, target):
        return False
    dx = target.x - site.x
    dy = target.y - site.y
    if dx * dx + dy * dy > max_squared_distance:
        return False
    tile = context.tiles.get(target)
    if tile is None:
        return True
    if tile.environment in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
        return False
    if tile.builder_bot_id not in (None, actor_id):
        return False
    if tile.building_team not in (None, team):
        return False
    if tile.building_type in (
        EntityType.BARRIER,
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
        EntityType.LAUNCHER,
        EntityType.HARVESTER,
        EntityType.FOUNDRY,
    ):
        return False
    return True


def choose_bridge_target(
    context: TurnContext,
    *,
    site: Position,
    team: Team,
    focus: Position,
    preferred_direction: Direction | None = None,
    avoid: Position | None = None,
    actor_id: int,
) -> Position | None:
    if preferred_direction is not None:
        candidate = site.add(preferred_direction)
        if bridge_target_is_valid(
            context,
            site=site,
            target=candidate,
            team=team,
            actor_id=actor_id,
            avoid=avoid,
        ):
            return candidate

    candidates: list[tuple[int, int, int, int, Position]] = []
    for idx, direction in enumerate(CARDINAL_DIRECTIONS):
        candidate = site.add(direction)
        if not bridge_target_is_valid(
            context,
            site=site,
            target=candidate,
            team=team,
            actor_id=actor_id,
            avoid=avoid,
        ):
            continue
        candidates.append(
            (
                manhattan_distance(candidate, focus),
                idx,
                candidate.x,
                candidate.y,
                candidate,
            )
        )
    if not candidates:
        return None
    return min(candidates)[4]
