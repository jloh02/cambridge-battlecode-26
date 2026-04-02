"""Controller-to-context translation.

The engine's public API is intentionally low level and ID based. This module
keeps that low-level cost at the boundary so solution code can work with one
readable snapshot of the current turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cambc import Controller, EntityType, Environment, GameError, Position, ResourceType, Team


TURRET_ENTITY_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}
ENTITY_TYPES_WITH_DIRECTION = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    *TURRET_ENTITY_TYPES,
}
ENTITY_TYPES_WITH_STORED_RESOURCE = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
}


@dataclass(slots=True)
class TileInfo:
    position: Position
    environment: Environment
    building_id: int | None = None
    building_type: EntityType | None = None
    building_team: Team | None = None
    builder_bot_id: int | None = None
    marker_value: int | None = None


@dataclass(slots=True)
class EntityInfo:
    entity_id: int
    team: Team
    entity_type: EntityType
    position: Position
    hp: int
    direction: object | None = None
    bridge_target: Position | None = None
    action_cooldown: int | None = None
    move_cooldown: int | None = None
    stored_resource: ResourceType | None = None
    stored_resource_id: int | None = None
    ammo_type: ResourceType | None = None
    ammo_amount: int | None = None
    marker_value: int | None = None


@dataclass(slots=True)
class TurnContext:
    entity_id: int
    team: Team
    entity_type: EntityType
    position: Position
    hp: int
    max_hp: int
    round_num: int
    titanium: int
    axionite: int
    scale_percent: float
    unit_count: int
    cpu_time_us: int
    action_cooldown: int
    move_cooldown: int
    vision_radius_sq: int
    map_width: int
    map_height: int
    attackable_tiles: list[Position] = field(default_factory=list)
    tiles: dict[Position, TileInfo] = field(default_factory=dict)
    entities: dict[int, EntityInfo] = field(default_factory=dict)
    visible_ore_tiles: list[Position] = field(default_factory=list)
    _friendly_entities_cache: list[EntityInfo] | None = field(default=None, init=False, repr=False)
    _enemy_entities_cache: list[EntityInfo] | None = field(default=None, init=False, repr=False)
    _visible_friendly_markers_cache: list[TileInfo] | None = field(default=None, init=False, repr=False)
    _visible_cores_cache: list[EntityInfo] | None = field(default=None, init=False, repr=False)

    @property
    def friendly_entities(self) -> list[EntityInfo]:
        if self._friendly_entities_cache is None:
            self._friendly_entities_cache = [
                entity for entity in self.entities.values() if entity.team == self.team
            ]
        return self._friendly_entities_cache

    @property
    def enemy_entities(self) -> list[EntityInfo]:
        if self._enemy_entities_cache is None:
            self._enemy_entities_cache = [
                entity for entity in self.entities.values() if entity.team != self.team
            ]
        return self._enemy_entities_cache

    @property
    def visible_friendly_markers(self) -> list[TileInfo]:
        if self._visible_friendly_markers_cache is None:
            self._visible_friendly_markers_cache = [
                tile
                for tile in self.tiles.values()
                if tile.building_type == EntityType.MARKER and tile.building_team == self.team
            ]
        return self._visible_friendly_markers_cache

    @property
    def visible_cores(self) -> list[EntityInfo]:
        if self._visible_cores_cache is None:
            self._visible_cores_cache = [
                entity
                for entity in self.friendly_entities
                if entity.entity_type == EntityType.CORE
            ]
        return self._visible_cores_cache


def _safe_call(callable_obj, *args):
    try:
        return callable_obj(*args)
    except GameError:
        return None


def sense_turn(controller: Controller) -> TurnContext:
    """Build a readable context snapshot from the raw controller."""

    entity_id = controller.get_id()
    position = controller.get_position()
    context = TurnContext(
        entity_id=entity_id,
        team=controller.get_team(),
        entity_type=controller.get_entity_type(),
        position=position,
        hp=controller.get_hp(),
        max_hp=controller.get_max_hp(),
        round_num=controller.get_current_round(),
        titanium=controller.get_global_resources()[0],
        axionite=controller.get_global_resources()[1],
        scale_percent=controller.get_scale_percent(),
        unit_count=controller.get_unit_count(),
        # Filled at the end of sensing so strategy time budgeting can include
        # snapshot-construction cost as well as pure decision cost.
        cpu_time_us=0,
        action_cooldown=controller.get_action_cooldown(),
        move_cooldown=controller.get_move_cooldown(),
        vision_radius_sq=controller.get_vision_radius_sq(),
        map_width=controller.get_map_width(),
        map_height=controller.get_map_height(),
    )

    if context.entity_type in TURRET_ENTITY_TYPES and hasattr(controller, "get_attackable_tiles"):
        attackable = _safe_call(controller.get_attackable_tiles)
        if attackable:
            context.attackable_tiles = attackable if isinstance(attackable, list) else list(attackable)

    entity_type_cache: dict[int, EntityType] = {entity_id: context.entity_type}
    entity_team_cache: dict[int, Team] = {entity_id: context.team}
    visible_entity_positions: dict[int, Position] = {entity_id: position}

    def cached_entity_type(target_id: int) -> EntityType:
        value = entity_type_cache.get(target_id)
        if value is not None:
            return value
        resolved = controller.get_entity_type(target_id)
        entity_type_cache[target_id] = resolved
        return resolved

    def cached_entity_team(target_id: int) -> Team:
        value = entity_team_cache.get(target_id)
        if value is not None:
            return value
        resolved = controller.get_team(target_id)
        entity_team_cache[target_id] = resolved
        return resolved

    for tile_position in controller.get_nearby_tiles(context.vision_radius_sq):
        building_id = controller.get_tile_building_id(tile_position)
        if building_id is not None:
            visible_entity_positions.setdefault(building_id, tile_position)
        building_type = cached_entity_type(building_id) if building_id is not None else None
        building_team = cached_entity_team(building_id) if building_id is not None else None
        marker_value = None
        if building_type == EntityType.MARKER and building_team == context.team:
            marker_value = controller.get_marker_value(building_id)
        builder_bot_id = controller.get_tile_builder_bot_id(tile_position)
        if builder_bot_id is not None:
            visible_entity_positions.setdefault(builder_bot_id, tile_position)

        tile_info = TileInfo(
            position=tile_position,
            environment=controller.get_tile_env(tile_position),
            building_id=building_id,
            building_type=building_type,
            building_team=building_team,
            builder_bot_id=builder_bot_id,
            marker_value=marker_value,
        )
        context.tiles[tile_position] = tile_info
        if tile_info.environment in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            context.visible_ore_tiles.append(tile_position)

    for nearby_id, nearby_position in visible_entity_positions.items():
        entity_type = cached_entity_type(nearby_id)
        entity_team = cached_entity_team(nearby_id)
        is_self = nearby_id == entity_id
        direction = (
            _safe_call(controller.get_direction, nearby_id)
            if entity_type in ENTITY_TYPES_WITH_DIRECTION
            else None
        )
        stored_resource = None
        if entity_type in ENTITY_TYPES_WITH_STORED_RESOURCE:
            stored_resource = _safe_call(controller.get_stored_resource, nearby_id)
        bridge_target = None
        if entity_type == EntityType.BRIDGE and hasattr(controller, "get_bridge_target"):
            bridge_target = _safe_call(controller.get_bridge_target, nearby_id)
        ammo_type = None
        ammo_amount = None
        if is_self and entity_type in TURRET_ENTITY_TYPES:
            ammo_type = _safe_call(controller.get_ammo_type)
            ammo_amount = _safe_call(controller.get_ammo_amount)
        context.entities[nearby_id] = EntityInfo(
            entity_id=nearby_id,
            team=entity_team,
            entity_type=entity_type,
            position=context.position if is_self else nearby_position,
            hp=context.hp if is_self else controller.get_hp(nearby_id),
            direction=direction,
            bridge_target=bridge_target,
            action_cooldown=context.action_cooldown if is_self else None,
            move_cooldown=context.move_cooldown if is_self else None,
            stored_resource=stored_resource,
            stored_resource_id=None,
            # The public API only exposes ammo getters on "this unit", not on an
            # arbitrary entity id. We therefore record ammo details only for the
            # current unit and leave other visible turrets as structurally typed
            # entities with HP/position/team/direction information.
            ammo_type=ammo_type,
            ammo_amount=ammo_amount,
            marker_value=None,
        )
    context.cpu_time_us = controller.get_cpu_time_elapsed()
    return context
