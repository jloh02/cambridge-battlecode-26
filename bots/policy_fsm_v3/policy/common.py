"""Shared solution helpers.

The two MVP strategies intentionally share movement, marker, and routing
helpers. That keeps the strategy differences focused on high-level policy
choices instead of copy-pasted controller trivia.
"""

from __future__ import annotations

from dataclasses import dataclass

from cambc import Direction, EntityType, Environment, GameConstants, Position

from bots.policy_fsm_v3.runtime.decision import (
    BuildDecision,
    BuildKind,
    MarkerDecision,
    MoveDecision,
    TurnPlan,
)
from bots.policy_fsm_v3.runtime.markers import (
    MarkerKind,
    decode_marker,
    encode_claim,
    encode_defense_alert,
    encode_route,
    is_recent_marker,
)
from bots.policy_fsm_v3.runtime.nav import (
    CARDINAL_DIRECTIONS,
    adjacent_all,
    adjacent_cardinals,
    direction_priority_toward,
    find_path_to_visible_goal,
    is_buildable_empty_ground,
    manhattan_distance,
    nearest_visible_ore,
)
from bots.policy_fsm_v3.runtime.sense import EntityInfo, TileInfo, TurnContext


PREFERRED_CARDINALS = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]


@dataclass(slots=True)
class AdjacentOre:
    position: Position
    tile: TileInfo


class BaseTrailSolution:
    """Base class for readable builder/core strategies.

    The base class owns per-unit memory:
    - core instances remember how many builders they have spawned
    - builder instances remember their exploration trail and current mode

    That matches the real engine model: one Player instance per unit, no shared
    Python globals, and markers for anything that needs to survive across units.
    """

    def __init__(self):
        self.spawned_builders = 0
        self.anchor_position: Position | None = None
        self.preferred_direction: Direction | None = None
        self.trail: list[Position] = []
        self.mode = "explore"
        self.target_ore: Position | None = None
        self.target_resource_env: Environment | None = None

    def initialise_builder_memory(self, context: TurnContext) -> None:
        if self.anchor_position is None:
            # Builders spawn on a core tile, so the first observed position is a
            # valid "home anchor" for route-building even after the core leaves vision.
            self.anchor_position = context.position
        if self.preferred_direction is None:
            self.preferred_direction = PREFERRED_CARDINALS[context.entity_id % len(PREFERRED_CARDINALS)]
        self.remember_position(context.position)

    def remember_position(self, position: Position) -> None:
        if not self.trail:
            self.trail = [position]
            return
        if self.trail[-1] == position:
            return
        if position in self.trail:
            self.trail = self.trail[: self.trail.index(position) + 1]
            return
        self.trail.append(position)

    def visible_enemy(self, context: TurnContext) -> EntityInfo | None:
        if not context.enemy_entities:
            return None
        return min(
            context.enemy_entities,
            key=lambda entity: manhattan_distance(context.position, entity.position),
        )

    def fresh_defense_alerts(self, context: TurnContext) -> list[TileInfo]:
        alerts: list[TileInfo] = []
        for tile in context.visible_friendly_markers:
            if tile.marker_value is None:
                continue
            message = decode_marker(tile.marker_value)
            if message is None or message.kind != MarkerKind.DEFENSE_ALERT:
                continue
            if is_recent_marker(context.round_num, message, horizon=12):
                alerts.append(tile)
        return alerts

    def build_defense_alert(self, context: TurnContext) -> MarkerDecision | None:
        for candidate in adjacent_cardinals(context.position):
            tile = context.tiles.get(candidate)
            if tile is None:
                continue
            if tile.building_type not in (None, EntityType.MARKER):
                continue
            return MarkerDecision(candidate, encode_defense_alert(context.round_num, threat_score=1))
        return None

    def adjacent_ores(self, context: TurnContext) -> list[AdjacentOre]:
        ores: list[AdjacentOre] = []
        for position in adjacent_cardinals(context.position):
            tile = context.tiles.get(position)
            if tile is None:
                continue
            if tile.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                ores.append(AdjacentOre(position, tile))
        return ores

    def tile_is_claimed(self, context: TurnContext, tile: TileInfo) -> bool:
        if tile.marker_value is None:
            return False
        message = decode_marker(tile.marker_value)
        if message is None:
            return False
        if message.kind not in (MarkerKind.CLAIM_TITANIUM, MarkerKind.CLAIM_AXIONITE):
            return False
        return is_recent_marker(context.round_num, message, horizon=20)

    def claim_ore(self, context: TurnContext, ore: AdjacentOre) -> MarkerDecision | None:
        if self.tile_is_claimed(context, ore.tile):
            return None
        return MarkerDecision(
            ore.position,
            encode_claim(ore.tile.environment, context.entity_id, context.round_num),
        )

    def choose_spawn_position(self, context: TurnContext) -> Position | None:
        """Try to spawn on the core tile that best points toward visible titanium."""

        targets = [
            tile.position
            for tile in context.tiles.values()
            if tile.building_type == EntityType.CORE and tile.building_team == context.team
        ]
        if not targets:
            return None
        if context.visible_ore_tiles:
            titanium_tiles = [
                position
                for position in context.visible_ore_tiles
                if context.tiles[position].environment == Environment.ORE_TITANIUM
            ]
            target = titanium_tiles[0] if titanium_tiles else context.visible_ore_tiles[0]
            targets.sort(key=lambda position: manhattan_distance(position, target))
        return targets[0]

    def defensive_build_plan(self, context: TurnContext) -> TurnPlan | None:
        enemy = self.visible_enemy(context)
        if enemy is None:
            return None
        build_direction = context.position.direction_to(enemy.position)
        for candidate in adjacent_all(context.position):
            tile = context.tiles.get(candidate)
            if tile is None:
                continue
            if tile.environment == Environment.WALL:
                continue
            if tile.building_type in (EntityType.CORE, EntityType.HARVESTER, EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH):
                continue
            return TurnPlan(
                action=BuildDecision(
                    kind=BuildKind.GUNNER,
                    position=candidate,
                    direction=build_direction,
                    replace_existing=tile.building_type in (EntityType.ROAD, EntityType.MARKER, EntityType.CONVEYOR),
                ),
                note="build defensive gunner",
            )
        return None

    def route_home_plan(self, context: TurnContext) -> TurnPlan:
        """Convert the builder's breadcrumb trail into conveyors on the way home."""

        if len(self.trail) <= 1:
            self.mode = "explore"
            self.target_ore = None
            self.target_resource_env = None
            return TurnPlan(note="route complete")

        current_index = self.trail.index(context.position) if context.position in self.trail else len(self.trail) - 1
        if current_index <= 0:
            self.mode = "explore"
            self.target_ore = None
            self.target_resource_env = None
            return TurnPlan(note="route complete")

        next_position = self.trail[current_index - 1]
        next_direction = context.position.direction_to(next_position)
        current_tile = context.tiles.get(context.position)
        action = None
        marker = None

        if current_tile is not None and current_tile.building_type != EntityType.CORE:
            if current_tile.environment == Environment.EMPTY:
                action = BuildDecision(
                    kind=BuildKind.CONVEYOR,
                    position=context.position,
                    direction=next_direction,
                    replace_existing=current_tile.building_type in (EntityType.ROAD, EntityType.MARKER, EntityType.CONVEYOR),
                )
            # Route markers are a cheap hint for any other builder that arrives
            # before the current one finishes the whole chain.
            if current_tile.building_type in (None, EntityType.MARKER):
                marker = MarkerDecision(context.position, encode_route(next_direction, context.round_num))

        self.trail = self.trail[: current_index + 1]
        return TurnPlan(
            marker=marker,
            action=action,
            move=MoveDecision(next_direction),
            note="convert breadcrumb trail into conveyors",
        )

    def choose_ore_targets(
        self,
        context: TurnContext,
        *,
        prefer_titanium: bool,
        allow_axionite: bool,
    ) -> set[Position]:
        target = nearest_visible_ore(
            context,
            prefer_titanium=prefer_titanium,
            allow_axionite=allow_axionite,
        )
        if target is None:
            return set()
        goals = {
            position
            for position in adjacent_cardinals(target)
            if position in context.tiles
        }
        return goals

    def explore_or_seek_plan(
        self,
        context: TurnContext,
        *,
        prefer_titanium: bool,
        allow_axionite: bool,
    ) -> TurnPlan:
        goals = self.choose_ore_targets(
            context,
            prefer_titanium=prefer_titanium,
            allow_axionite=allow_axionite,
        )
        if goals:
            path = find_path_to_visible_goal(context, context.position, goals)
            if path:
                next_position = path[0]
                direction = context.position.direction_to(next_position)
                next_tile = context.tiles.get(next_position)
                build_action = None
                if is_buildable_empty_ground(next_tile):
                    build_action = BuildDecision(
                        kind=BuildKind.ROAD,
                        position=next_position,
                        replace_existing=next_tile.building_type == EntityType.MARKER if next_tile else False,
                    )
                return TurnPlan(
                    action=build_action,
                    move=MoveDecision(direction),
                    note="move toward visible ore",
                )

        preferred_direction = self.preferred_direction or Direction.NORTH
        for direction in [preferred_direction] + [candidate for candidate in CARDINAL_DIRECTIONS if candidate != preferred_direction]:
            next_position = context.position.add(direction)
            tile = context.tiles.get(next_position)
            if tile is None or tile.environment != Environment.EMPTY:
                continue
            build_action = None
            if tile.building_type in (None, EntityType.MARKER):
                build_action = BuildDecision(
                    kind=BuildKind.ROAD,
                    position=next_position,
                    replace_existing=tile.building_type == EntityType.MARKER,
                )
            return TurnPlan(
                action=build_action,
                move=MoveDecision(direction),
                note="continue outward exploration",
            )
        return TurnPlan(note="idle because all visible exits are blocked")
